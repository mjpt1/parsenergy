"""The eight-stage sales funnel, manual leads, case notes and stop reasons."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.plants.models import Plant
from apps.requests.models import ProjectContract, Request, RequestContract, RequestMessageLog, RequestStageNote
from apps.requests.services import lifecycle, offers

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}
F = Request.FunnelStage


def person(role):
    return User.objects.create_user(username=f'u_{role}', password='p', role=role)


def lead(mobile='09120000031'):
    return lifecycle.create_request(full_name='مشتری آزمایشی', mobile=mobile, province='تهران')


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class FunnelFlowTests(TestCase):
    def setUp(self):
        self.mkt, self.sales, self.tech, self.boss = (person(r) for r in ('marketing', 'sales', 'technical', 'admin'))

    def test_full_path_moves_through_every_stage_and_texts_the_customer(self):
        req = lead()
        self.assertEqual(req.funnel_stage, F.LEAD)
        lifecycle.refer_marketing_to_sales(req, actor=self.mkt)
        self.assertEqual(req.funnel_stage, F.QUALIFICATION)
        lifecycle.refer_sales_to_technical(req, actor=self.sales)
        self.assertEqual(req.funnel_stage, F.INITIAL_DESIGN)
        offer = offers.add_offer(request=req, title='طرح', amount=100)
        lifecycle.refer_to_sales(req, actor=self.tech)
        self.assertEqual(req.funnel_stage, F.FIRST_CONTRACT)
        with self.assertRaises(lifecycle.DepartmentError):
            lifecycle.start_commercial_offer(req, actor=self.sales)
        RequestContract.objects.create(request=req, offer=offer, contract_number='F-1', body='x',
                                       status=RequestContract.Status.APPROVED)
        lifecycle.start_commercial_offer(req, actor=self.sales)
        self.assertEqual((req.funnel_stage, req.department), (F.COMMERCIAL_OFFER, Request.Department.TECHNICAL))
        lifecycle.refer_to_sales(req, actor=self.tech)
        self.assertEqual(req.funnel_stage, F.SECOND_CONTRACT)
        with self.assertRaises(lifecycle.DepartmentError):
            lifecycle.close_by_sales(req, actor=self.sales)
        ProjectContract.objects.create(request=req, contract_number='P-1', signed_on='2026-11-18', total_amount=3)
        lifecycle.close_by_sales(req, actor=self.sales)
        self.assertEqual(req.funnel_stage, F.EXECUTION)
        with self.assertRaises(lifecycle.DepartmentError):
            lifecycle.start_operation(req, actor=self.tech)
        req.plant = Plant.objects.create(name='ن', owner=self.boss, external_code='F-P', location_name='ی',
                                         latitude=Decimal('31'), longitude=Decimal('54'), capacity_kw=1)
        req.save()
        lifecycle.start_operation(req, actor=self.tech)
        self.assertEqual(req.funnel_stage, F.OPERATION)
        moves = req.stage_notes.filter(kind=RequestStageNote.Kind.MOVE).count()
        self.assertEqual(moves, 7)
        labels = req.message_logs.filter(message_type=RequestMessageLog.MessageType.STATUS_CHANGE)
        self.assertTrue(labels.filter(body__contains=F.OPERATION.label).exists())

    def test_stop_needs_a_reason_and_keeps_the_stage(self):
        req = lead()
        lifecycle.refer_marketing_to_sales(req, actor=self.mkt)
        self.client.force_login(self.sales)
        url = reverse('requests:admin-status', args=[req.pk])
        self.client.post(url, {'status': 'closed'}, **HOST)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.NEW)
        self.client.post(url, {'status': 'closed', 'reason': 'competitor', 'note': 'قیمت'}, **HOST)
        req.refresh_from_db()
        self.assertEqual((req.status, req.funnel_stage, req.stop_reason),
                         (Request.Status.CLOSED, F.QUALIFICATION, 'competitor'))
        self.assertTrue(req.stage_notes.filter(kind=RequestStageNote.Kind.STOP).exists())

    def test_only_the_team_holding_the_case_can_stop_it(self):
        req = lead()
        self.client.force_login(self.tech)
        self.client.post(reverse('requests:admin-status', args=[req.pk]),
                         {'status': 'cancelled', 'reason': 'budget'}, **HOST)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.NEW)

    def test_technical_sees_only_technical_history(self):
        req = lead()
        lifecycle.add_note(req, 'مذاکره محرمانه', actor=self.mkt)
        lifecycle.refer_marketing_to_sales(req, actor=self.mkt)
        lifecycle.refer_sales_to_technical(req, actor=self.sales)
        lifecycle.add_note(req, 'بازدید فنی', actor=self.tech)
        self.client.force_login(self.tech)
        page = self.client.get(reverse('requests:admin-detail', args=[req.pk]), **HOST)
        self.assertContains(page, 'بازدید فنی')
        self.assertNotContains(page, 'مذاکره محرمانه')

    def test_management_correction_needs_a_reason(self):
        req = lead()
        self.client.force_login(self.boss)
        url = reverse('requests:admin-funnel-set', args=[req.pk])
        self.client.post(url, {'stage': 'execution'}, **HOST)
        req.refresh_from_db()
        self.assertEqual(req.funnel_stage, F.LEAD)
        self.client.post(url, {'stage': 'execution', 'note': 'اصلاح سابقه'}, **HOST)
        req.refresh_from_db()
        self.assertEqual((req.funnel_stage, req.department), (F.EXECUTION, Request.Department.DONE))
        self.assertFalse(req.message_logs.exists())

    def test_board_and_stage_filter(self):
        req = lead()
        self.client.force_login(self.boss)
        board = self.client.get(reverse('requests:admin-funnel'), **HOST)
        self.assertEqual(board.status_code, 200)
        self.assertContains(board, req.full_name)
        rows = self.client.get(reverse('requests:admin-list'), {'funnel_stage': 'operation'}, **HOST)
        self.assertEqual(list(rows.context['requests']), [])


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class ManualLeadTests(TestCase):
    data = {'full_name': 'شرکت نمونه', 'mobile': '۰۹۱۲۰۰۰۰۰۴۱', 'user_type': 'legal', 'province': 'تهران',
            'city': 'تهران', 'priority': 'normal'}

    def test_marketing_lead_starts_at_the_top_of_the_funnel(self):
        self.client.force_login(person('marketing'))
        response = self.client.post(reverse('requests:admin-lead-create'), self.data, **HOST)
        req = Request.objects.get(mobile='09120000041')
        self.assertRedirects(response, reverse('requests:admin-detail', args=[req.pk]), fetch_redirect_response=False)
        self.assertEqual((req.funnel_stage, req.lead_source), (F.LEAD, 'manual'))

    def test_sales_lead_goes_to_its_own_qualification(self):
        sales = person('sales')
        self.client.force_login(sales)
        self.client.post(reverse('requests:admin-lead-create'), self.data, **HOST)
        req = Request.objects.get(mobile='09120000041')
        self.assertEqual((req.funnel_stage, req.sales_assignee), (F.QUALIFICATION, sales))

    def test_technical_cannot_create_or_edit(self):
        req = lead()
        lifecycle.refer_marketing_to_sales(req)
        lifecycle.refer_sales_to_technical(req)
        self.client.force_login(person('technical'))
        self.assertEqual(self.client.get(reverse('requests:admin-lead-create'), **HOST).status_code, 403)
        self.assertEqual(self.client.get(reverse('requests:admin-lead-edit', args=[req.pk]), **HOST).status_code, 403)

    def test_edit_is_logged_and_linked_mobile_stays(self):
        customer = User.objects.create_user(username='09120000031', password='p', role='customer')
        req = lead()
        req.user = customer
        req.save()
        self.client.force_login(person('marketing'))
        self.client.post(reverse('requests:admin-lead-edit', args=[req.pk]),
                         {**self.data, 'full_name': 'نام تازه'}, **HOST)
        req.refresh_from_db()
        self.assertEqual((req.full_name, req.mobile), ('نام تازه', '09120000031'))
        self.assertTrue(req.stage_notes.filter(kind=RequestStageNote.Kind.EDIT).exists())

    def test_customer_cannot_change_plants(self):
        customer = User.objects.create_user(username='cust', password='p', role='customer')
        plant = Plant.objects.create(name='ن', owner=customer, external_code='C-P', location_name='ی',
                                     latitude=Decimal('31'), longitude=Decimal('54'), capacity_kw=1)
        self.client.force_login(customer)
        for url in (reverse('plants:create'), reverse('plants:inverter-create'),
                    reverse('plants:edit', args=[plant.pk]), reverse('plants:delete', args=[plant.pk])):
            self.assertEqual(self.client.get(url, **HOST).status_code, 403, url)


class ExistingCaseMigrationTests(TestCase):
    def test_cases_land_on_the_stage_their_history_shows(self):
        from importlib import import_module

        from django.apps import apps
        from django.utils import timezone

        def case(mobile, **values):
            req = lead(mobile)
            Request.objects.filter(pk=req.pk).update(funnel_stage=F.LEAD, **values)
            return req

        now = timezone.now()
        negotiating = case('09120000051', department='sales', sales_phase='negotiation')
        technical = case('09120000052', department='technical')
        won = case('09120000053', department='done')
        lost = case('09120000054', department='done', status='closed', triaged_at=now)
        import_module('apps.requests.migrations.0023_sales_funnel').place_existing_requests(apps, None)
        stage = lambda req: Request.objects.get(pk=req.pk).funnel_stage
        self.assertEqual(stage(negotiating), F.FIRST_CONTRACT)
        self.assertEqual(stage(technical), F.INITIAL_DESIGN)
        self.assertEqual(stage(won), F.EXECUTION)
        self.assertEqual(stage(lost), F.INITIAL_DESIGN)


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class SeniorMarketingTests(TestCase):
    def test_only_the_granted_marketer_sees_leads_beyond_the_queue(self):
        from apps.accounts.models import Permission
        from apps.requests import repositories

        moved = lead()
        lifecycle.refer_marketing_to_sales(moved)
        ordinary = User.objects.create_user(username='m1', password='p', role='marketing')
        senior = User.objects.create_user(username='m2', password='p', role='marketing')
        senior.extra_permissions.add(Permission.objects.get(code='leads.view_all'))
        visible = lambda user: repositories.scope_requests_by_department(user, Request.objects.all())
        self.assertFalse(visible(ordinary).filter(pk=moved.pk).exists())
        self.assertTrue(visible(senior).filter(pk=moved.pk).exists())
        self.assertFalse(repositories.owns_current_stage(senior, moved))
