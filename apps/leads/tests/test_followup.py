"""Registration SMS, form-stage follow-up, the marketer report and the card."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.leads.models import Lead, LeadSource
from apps.requests.models import Request, RequestMessageLog

User = get_user_model()


class _Base(TestCase):
    def setUp(self):
        self.marketer = User.objects.create_user(
            username='mk1', password='Zx9!kQ2mVr7t', role='marketing', first_name='سارا')
        self.other = User.objects.create_user(
            username='mk2', password='Zx9!kQ2mVr7t', role='marketing')
        self.boss = User.objects.create_user(
            username='boss', password='Zx9!kQ2mVr7t', role='admin')
        self.source = LeadSource.objects.create(name='غرفه', marketer=self.marketer)

    def _capture(self, **overrides):
        data = {'full_name': 'علی رضایی', 'mobile': '09123456789', 'company': 'نمونه',
                'country': 'ایران', 'province': 'تهران', 'city': 'تهران'}
        data.update(overrides)
        return self.client.post(
            reverse('leads:capture', kwargs={'token': self.source.token}), data)


class RegistrationSmsTests(_Base):
    def test_capture_sends_welcome_sms_with_stage_two_link(self):
        self._capture()
        lead = Lead.objects.get()
        log = RequestMessageLog.objects.get(message_type=RequestMessageLog.MessageType.LEAD)
        self.assertEqual(log.mobile, '09123456789')
        self.assertIn(lead.lead_code, log.body)
        self.assertIn(reverse('leads:detail-form', kwargs={'token': lead.resume_token}), log.body)


class LocationTests(_Base):
    def test_city_must_belong_to_the_province(self):
        resp = self._capture(province='تهران', city='تبریز')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Lead.objects.exists())

    def test_foreign_visitor_types_a_city_and_needs_no_province(self):
        resp = self._capture(country='ترکیه', province='', city='استانبول')
        self.assertEqual(resp.status_code, 302)
        lead = Lead.objects.get()
        self.assertEqual(lead.country, 'ترکیه')
        self.assertEqual(lead.request.city, 'استانبول')
        self.assertEqual(lead.request.province, '')


class FollowupTests(_Base):
    def setUp(self):
        super().setUp()
        self._capture()
        self._capture(mobile='09120000001')
        self.done, self.open = Lead.objects.order_by('pk')
        self.done.stage2_completed = True
        self.done.save()
        RequestMessageLog.objects.all().delete()

    def test_lists_split_by_stage(self):
        self.client.force_login(self.boss)
        resp = self.client.get(reverse('leads:followup'))
        self.assertEqual(resp.context['counts'], {'all': 2, 'stage2': 1, 'stage1': 1})
        self.assertEqual([l.pk for l in resp.context['leads']], [self.open.pk])

    def test_reminder_goes_only_to_incomplete_leads_and_not_twice_a_day(self):
        self.client.force_login(self.boss)
        url = reverse('leads:followup')
        self.client.post(url, {'scope': 'all'})
        self.client.post(url, {'scope': 'all'})
        self.client.post(url, {'lead': [self.done.pk]})
        logs = RequestMessageLog.objects.all()
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.get().mobile, self.open.request.mobile)
        self.open.refresh_from_db()
        self.assertEqual(self.open.reminder_count, 1)

        self.open.last_reminder_at = timezone.now() - timedelta(hours=25)
        self.open.save()
        self.client.post(url, {'lead': [self.open.pk]})
        self.assertEqual(RequestMessageLog.objects.count(), 2)

    def test_marketer_sees_only_own_leads(self):
        self.client.force_login(self.other)
        resp = self.client.get(reverse('leads:followup') + '?stage=all')
        self.assertEqual(resp.context['counts']['all'], 0)
        self.client.post(reverse('leads:followup'), {'scope': 'all'})
        self.assertFalse(RequestMessageLog.objects.exists())


class MarketerReportTests(_Base):
    def setUp(self):
        super().setUp()
        self._capture()
        self._capture(mobile='09120000001')
        lead = Lead.objects.first()
        lead.stage2_completed = True
        lead.temperature = Lead.Temperature.HOT
        lead.save()
        Request.objects.filter(pk=lead.request_id).update(
            status=Request.Status.PAID, department=Request.Department.DONE)

    def test_counts_per_marketer(self):
        self.client.force_login(self.boss)
        resp = self.client.get(reverse('leads:marketer-report'))
        row = next(r for r in resp.context['rows'] if r['marketer'] == self.marketer)
        self.assertEqual((row['total'], row['stage2'], row['hot'], row['won'], row['referred']),
                         (2, 1, 1, 1, 1))
        self.assertEqual(row['stage2_pct'], 50)
        empty = next(r for r in resp.context['rows'] if r['marketer'] == self.other)
        self.assertEqual(empty['total'], 0)

    def test_print_excel_and_detail(self):
        self.client.force_login(self.boss)
        url = reverse('leads:marketer-report')
        self.assertContains(self.client.get(url + '?print=1'), 'window.print')
        resp = self.client.get(url + '?export=excel')
        self.assertIn('spreadsheetml', resp['Content-Type'])
        detail = self.client.get(reverse('leads:marketer-detail', args=[self.marketer.pk]))
        self.assertEqual(detail.context['summary']['total'], 2)

    def test_marketers_cannot_open_the_report(self):
        self.client.force_login(self.marketer)
        self.assertEqual(self.client.get(reverse('leads:marketer-report')).status_code, 403)


class BusinessCardTests(TestCase):
    def test_qr_only_page_points_to_card(self):
        from unittest import mock
        from django.core.cache import cache
        from apps.core import card
        cache.clear()
        with mock.patch.object(card, '_qr_svg', wraps=card._qr_svg) as qr:
            resp = self.client.get(reverse('card-qr'))
        qr.assert_called_once_with('https://pars-tida.ir/card/')
        self.assertContains(resp, '<svg')
        self.assertNotContains(resp, 'پارس انرژی تیدا')  # nothing but the code

    def test_card_and_vcard(self):
        resp = self.client.get(reverse('card'))
        self.assertContains(resp, '<svg')
        self.assertContains(resp, 'پارس انرژی تیدا')
        vcf = self.client.get(reverse('card-vcf'))
        body = vcf.content.decode('utf-8')
        self.assertTrue(body.startswith('BEGIN:VCARD\r\n'))
        self.assertIn('TEL;TYPE=WORK,VOICE:+982122222922', body)
        self.assertIn('TEL;TYPE=CELL:+989198333303', body)
        self.assertNotIn('instagram', body)
        self.assertContains(resp, 'tel:+989198333303')
        self.assertContains(resp, 'https://t.me/+989198333303')
        self.assertNotContains(resp, 'instagram')
        self.assertNotContains(resp, 'x.com')
        self.assertIn('attachment', vcf['Content-Disposition'])


class SalesFollowupTests(_Base):
    def test_sales_sees_every_lead_and_can_remind(self):
        self._capture()
        RequestMessageLog.objects.all().delete()
        sales = User.objects.create_user(username='s1', password='Zx9!kQ2mVr7t', role='sales')
        self.client.force_login(sales)
        resp = self.client.get(reverse('leads:followup'))
        self.assertEqual(resp.context['counts']['stage1'], 1)
        self.client.post(reverse('leads:followup'), {'scope': 'all'})
        self.assertEqual(RequestMessageLog.objects.count(), 1)
