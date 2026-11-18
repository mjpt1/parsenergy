"""The management dashboard's data layer, and the financial role.

The point of most of these is that the dashboard never invents a number: when
there is nothing to divide by, the metric is None and the template shows a
dash. A confident "0%" on an empty system is worse than an honest blank.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.alerts.models import AlertEvent, AlertRule
from apps.plants.models import Plant
from apps.requests import repositories
from apps.requests.executive_metrics import _pct, build_executive_metrics, build_nav_counts
from apps.requests.models import Request
from apps.requests.services import lifecycle

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}


def _plant(owner, name, code, kw):
    return Plant.objects.create(
        name=name, owner=owner, external_code=code, location_name='تهران',
        latitude=35.7, longitude=51.4, capacity_kw=kw)


class PercentHelperTests(TestCase):
    def test_zero_denominator_is_unknown_not_zero(self):
        self.assertIsNone(_pct(0, 0))
        self.assertIsNone(_pct(5, 0))

    def test_ordinary_percentage(self):
        self.assertEqual(_pct(1, 4), 25)
        self.assertEqual(_pct(1, 3, digits=1), 33.3)


class ExecutiveMetricsTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_user(
            username='exec_boss', password='p', is_superuser=True, is_staff=True)

    def test_empty_database_produces_no_invented_numbers(self):
        m = build_executive_metrics(self.boss)
        for key in ('conversion_pct', 'sla_compliance_pct', 'qualify_rate_pct',
                    'module_health_pct', 'avg_wait_hours', 'avg_ack_minutes'):
            self.assertIsNone(m[key], f'{key} should be None on an empty system')
        self.assertEqual(m['funnel'][0]['count'], 0)
        self.assertEqual(m['attention'], [])
        self.assertEqual(m['sla_rows'], [])

    def test_funnel_counts_each_stage(self):
        marketing = lifecycle.create_request(
            full_name='الف', mobile='09120008001', province='تهران')
        moved = lifecycle.create_request(
            full_name='ب', mobile='09120008002', province='تهران')
        lifecycle.refer_marketing_to_sales(moved, actor=self.boss)

        m = build_executive_metrics(self.boss)
        by_label = {s['label']: s['count'] for s in m['funnel']}
        self.assertEqual(by_label['ورودی لید'], 1)
        self.assertEqual(by_label['صلاحیت‌سنجی لید'], 1)
        self.assertEqual(marketing.department, Request.Department.MARKETING)

    def test_sla_compliance_never_exceeds_one_hundred(self):
        stale = lifecycle.create_request(
            full_name='کهنه', mobile='09120008003', province='تهران')
        Request.objects.filter(pk=stale.pk).update(
            stage_entered_at=timezone.now() - timedelta(hours=lifecycle.STAGE_SLA_HOURS + 5))
        fresh = lifecycle.create_request(
            full_name='تازه', mobile='09120008004', province='تهران')
        self.assertIsNotNone(fresh.stage_entered_at)

        m = build_executive_metrics(self.boss)
        self.assertEqual(m['overdue_count'], 1)
        self.assertEqual(m['sla_compliance_pct'], 50.0)

    def test_overdue_request_appears_in_attention_and_sla_table(self):
        req = lifecycle.create_request(
            full_name='دیرکرد', mobile='09120008005', province='یزد')
        Request.objects.filter(pk=req.pk).update(
            stage_entered_at=timezone.now() - timedelta(hours=lifecycle.STAGE_SLA_HOURS + 10))

        m = build_executive_metrics(self.boss)
        self.assertTrue(any(a['id'] == req.id and a['tone'] == 'bad' for a in m['attention']))
        row = next(r for r in m['sla_rows'] if r['id'] == req.id)
        self.assertTrue(row['overdue'])
        self.assertLess(row['remaining_h'], 0)

    def test_incomplete_lead_is_flagged_with_what_is_missing(self):
        req = lifecycle.create_request(
            full_name='ناقص', mobile='09120008006', province='فارس')
        m = build_executive_metrics(self.boss)
        item = next(a for a in m['attention'] if a['id'] == req.id)
        self.assertIn('قبض برق', item['reason'])
        self.assertIn('موقعیت نقشه', item['reason'])

    def test_capacity_sums_real_plants(self):
        owner = User.objects.create_user(username='exec_owner', password='p')
        _plant(owner, 'نیروگاه ۱', 'EXEC-1', 250)
        _plant(owner, 'نیروگاه ۲', 'EXEC-2', 800)
        m = build_executive_metrics(self.boss)
        self.assertEqual(m['plant_count'], 2)
        self.assertEqual(int(m['capacity_kw']), 1050)

    def test_nav_counts_are_plain_integers(self):
        counts = build_nav_counts(self.boss)
        for key, value in counts.items():
            self.assertIsInstance(value, int, f'{key} should be an int')


class AlertAcknowledgementClockTests(TestCase):
    """`acknowledged` said whether someone handled an alert, never when."""

    def setUp(self):
        owner = User.objects.create_user(username='ack_owner', password='p')
        plant = _plant(owner, 'نیروگاه', 'ACK-1', 10)
        self.rule = AlertRule.objects.create(
            plant=plant, name='دما', metric='temp', threshold_value=75)

    def test_acknowledging_stamps_the_time(self):
        event = AlertEvent.objects.create(rule=self.rule, message='داغ')
        self.assertIsNone(event.acknowledged_at)
        event.acknowledged = True
        event.save()
        self.assertIsNotNone(event.acknowledged_at)

    def test_un_acknowledging_clears_the_time(self):
        event = AlertEvent.objects.create(rule=self.rule, message='داغ', acknowledged=True)
        self.assertIsNotNone(event.acknowledged_at)
        event.acknowledged = False
        event.save()
        self.assertIsNone(event.acknowledged_at)

    def test_average_handling_time_reaches_the_dashboard(self):
        boss = User.objects.create_user(
            username='ack_boss', password='p', is_superuser=True, is_staff=True)
        event = AlertEvent.objects.create(rule=self.rule, message='داغ', acknowledged=True)
        AlertEvent.objects.filter(pk=event.pk).update(
            acknowledged_at=event.created_at + timedelta(minutes=30))
        self.assertEqual(build_executive_metrics(boss)['avg_ack_minutes'], 30)


class FinancialRoleTests(TestCase):
    """Finance reads the commercial tail; it never moves a request."""

    def setUp(self):
        self.finance = User.objects.create_user(
            username='fin1', password='p', role='financial')
        self.boss = User.objects.create_user(
            username='fin_boss', password='p', is_superuser=True, is_staff=True)
        self.lead = lifecycle.create_request(
            full_name='در بازاریابی', mobile='09120009001', province='تهران')
        self.deal = lifecycle.create_request(
            full_name='در فروش', mobile='09120009002', province='تهران')
        lifecycle.refer_marketing_to_sales(self.deal, actor=self.boss)

    def test_sees_sales_and_done_only(self):
        visible = repositories.scope_requests_by_department(
            self.finance, Request.objects.all())
        ids = set(visible.values_list('id', flat=True))
        self.assertIn(self.deal.id, ids)
        self.assertNotIn(self.lead.id, ids, 'marketing-stage leads are not finance business')

    def test_can_open_the_commercial_pages(self):
        self.client.force_login(self.finance)
        for name in ('requests:admin-contracts', 'requests:admin-payments'):
            self.assertEqual(self.client.get(reverse(name), **HOST).status_code, 200, name)

    def test_cannot_cancel_a_request(self):
        self.client.force_login(self.finance)
        self.client.post(reverse('requests:admin-status', args=[self.deal.id]),
                         {'status': Request.Status.CANCELLED}, **HOST)
        self.deal.refresh_from_db()
        self.assertNotEqual(self.deal.status, Request.Status.CANCELLED)

    def test_cannot_unlock_customer_edits(self):
        self.client.force_login(self.finance)
        self.client.post(reverse('requests:admin-toggle-edit', args=[self.deal.id]), **HOST)
        self.deal.refresh_from_db()
        self.assertFalse(self.deal.edit_unlocked)

    def test_management_can_still_cancel(self):
        """The finance guard must not catch anyone else."""
        self.client.force_login(self.boss)
        self.client.post(reverse('requests:admin-status', args=[self.deal.id]),
                         {'status': Request.Status.CANCELLED, 'reason': 'budget'}, **HOST)
        self.deal.refresh_from_db()
        self.assertEqual(self.deal.status, Request.Status.CANCELLED)

    def test_lands_on_a_working_dashboard(self):
        self.client.force_login(self.finance)
        response = self.client.get('/', follow=True, **HOST)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'داشبورد مالی')
        self.assertContains(response, 'accounts/logout')
