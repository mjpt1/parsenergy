"""What has to stay true about exhibition capture.

The headline promise: a lead captured at a stand is an ordinary request in the
marketing queue, and the pipeline treats it like any other.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.leads.models import Lead, LeadSource
from apps.requests.models import Request, RequestMessageLog
from apps.requests import repositories

User = get_user_model()


class CaptureFlowTests(TestCase):
    def setUp(self):
        self.marketer = User.objects.create_user(
            username='mk1', password='Zx9!kQ2mVr7t', role='marketing')
        self.source = LeadSource.objects.create(
            name='نمایشگاه تست', marketer=self.marketer, event_name='EXPO')

    def _capture(self, source=None, **overrides):
        data = {'full_name': 'علی رضایی', 'mobile': '09123456789',
                'company': 'شرکت نمونه', 'goals': ['sell_power', 'investment'],
                'timeline': 'lt_1m', 'contact_method': 'call',
                'province': 'تهران', 'city': 'تهران'}
        data.update(overrides)
        token = (source or self.source).token
        return self.client.post(reverse('leads:capture', kwargs={'token': token}), data)

    def test_capture_creates_a_request_in_the_marketing_queue(self):
        """The whole point of the rework: one pipeline, no parallel inbox."""
        resp = self._capture()
        self.assertEqual(resp.status_code, 302)
        req = Request.objects.get()
        self.assertEqual(req.department, Request.Department.MARKETING)
        self.assertEqual(req.how_heard, Request.HowHeard.EXHIBITION)
        self.assertEqual(req.full_name, 'علی رضایی')
        self.assertEqual(req.mobile, '09123456789')
        self.assertFalse(req.identity_verified)  # no Shahkar at a stand

    def test_exhibition_detail_is_attached_to_that_request(self):
        self._capture()
        req = Request.objects.get()
        lead = Lead.objects.get()
        self.assertEqual(lead.request, req)
        self.assertEqual(req.exhibition, lead)
        self.assertEqual(lead.marketer, self.marketer)
        self.assertEqual(lead.goals, ['sell_power', 'investment'])
        self.assertTrue(lead.lead_code)

    def test_visitor_cannot_choose_the_marketer(self):
        """Attribution comes from the link, so a posted marketer is ignored."""
        other = User.objects.create_user(username='mk2', password='Zx9!kQ2mVr7t',
                                         role='marketing')
        # Both fields are posted and both must be ignored.
        self._capture(**{'marketer': other.pk, 'event_name': 'جعلی'})
        lead = Lead.objects.get()
        self.assertEqual(lead.marketer, self.marketer)
        self.assertEqual(lead.source, self.source)
        self.assertEqual(lead.event_name, 'EXPO')

    def test_unknown_or_disabled_token_is_404(self):
        self.assertEqual(self.client.get(
            reverse('leads:capture', kwargs={'token': 'nope'})).status_code, 404)
        self.source.is_active = False
        self.source.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(
            reverse('leads:capture', kwargs={'token': self.source.token})).status_code, 404)

    def test_mobile_shapes_are_normalised(self):
        for raw in ('+989123456789', '۰۹۱۲۳۴۵۶۷۸۹', '0098 912 345 6789', '9123456789'):
            Lead.objects.all().delete()
            Request.objects.all().delete()
            self._capture(mobile=raw)
            self.assertEqual(Request.objects.get().mobile, '09123456789', raw)

    def test_bad_mobile_is_rejected(self):
        self._capture(mobile='12345')
        self.assertEqual(Request.objects.count(), 0)

    def test_stage_two_updates_the_same_request(self):
        """One lead, one request — the resume link never creates a second."""
        self._capture()
        lead = Lead.objects.get()
        resp = self.client.post(
            reverse('leads:detail-form', kwargs={'token': lead.resume_token}),
            {'install_location': 'rooftop', 'area_range': '500_2000',
             'shade_status': 'no', 'latitude': '35.7219', 'longitude': '51.3347',
             'area_note': 'حدود ۱۲۰۰ متر'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Request.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 1)

        req = Request.objects.get()
        lead.refresh_from_db()
        self.assertEqual(req.install_location, 'rooftop')
        self.assertEqual(req.area_range, '500_2000')
        self.assertEqual(str(req.latitude), '35.721900')
        self.assertEqual(lead.area_note, 'حدود ۱۲۰۰ متر')
        self.assertTrue(lead.stage2_completed)

    def test_capture_sends_exactly_one_registration_sms(self):
        """Reversed at the client's request (Oct 2026): registering texts the
        visitor a receipt with their stage-2 link — one message, no more."""
        self._capture()
        self.assertEqual(RequestMessageLog.objects.count(), 1)

    def test_capture_pages_are_not_indexable(self):
        self._capture()
        lead = Lead.objects.get()
        for name, kwargs in (('leads:capture', {'token': self.source.token}),
                             ('leads:detail-form', {'token': lead.resume_token}),
                             ('leads:done', {'token': lead.resume_token})):
            resp = self.client.get(reverse(name, kwargs=kwargs))
            self.assertIn('noindex', resp.headers.get('X-Robots-Tag', ''), name)

    def test_robots_txt_disallows_leads(self):
        self.assertIn('Disallow: /leads/', self.client.get('/robots.txt').content.decode())


class PipelineVisibilityTests(TestCase):
    """Who sees an exhibition lead, and when."""

    def setUp(self):
        self.a = User.objects.create_user(username='mka', password='Zx9!kQ2mVr7t',
                                          role='marketing')
        self.b = User.objects.create_user(username='mkb', password='Zx9!kQ2mVr7t',
                                          role='marketing')
        self.sales = User.objects.create_user(username='s1', password='Zx9!kQ2mVr7t',
                                              role='sales')
        self.tech = User.objects.create_user(username='t1', password='Zx9!kQ2mVr7t',
                                             role='technical')
        self.boss = User.objects.create_user(username='boss', password='Zx9!kQ2mVr7t',
                                             role='admin', is_superuser=True)

        def exhibition_lead(owner, name):
            req = Request.objects.create(
                full_name=name, mobile='09120000000', province='تهران',
                department=Request.Department.MARKETING,
                how_heard=Request.HowHeard.EXHIBITION)
            Lead.objects.create(request=req, marketer=owner)
            return req

        self.mine = exhibition_lead(self.a, 'مال من')
        self.theirs = exhibition_lead(self.b, 'مال دیگری')
        # A plain website lead: shared across marketing, as it always was.
        self.website = Request.objects.create(
            full_name='از سایت', mobile='09121111111', province='تهران',
            department=Request.Department.MARKETING)

    def _visible(self, user):
        qs = repositories.scope_requests_by_department(user, Request.objects.all())
        return set(qs.values_list('full_name', flat=True))

    def test_marketer_sees_own_exhibition_leads_and_website_leads(self):
        self.assertEqual(self._visible(self.a), {'مال من', 'از سایت'})
        self.assertEqual(self._visible(self.b), {'مال دیگری', 'از سایت'})

    def test_management_sees_everything(self):
        self.assertEqual(self._visible(self.boss),
                         {'مال من', 'مال دیگری', 'از سایت'})

    def test_sales_sees_every_lead_from_the_moment_it_lands(self):
        """No approval gate in front of sales: a new lead is theirs at once."""
        self.assertEqual(self._visible(self.sales),
                         {'مال من', 'مال دیگری', 'از سایت'})

    def test_technical_waits_for_the_referral(self):
        """Technical still only joins once the lead reaches their stage."""
        self.assertEqual(self._visible(self.tech), set())
        self.mine.department = Request.Department.TECHNICAL
        self.mine.save(update_fields=['department'])
        self.assertEqual(self._visible(self.tech), {'مال من'})

    def test_technical_does_not_see_the_customers_identity(self):
        """Same privacy rule as every other lead in the pipeline."""
        self.mine.department = Request.Department.TECHNICAL
        self.mine.save(update_fields=['department'])
        self.client.force_login(self.tech)
        body = self.client.get(reverse('requests:admin-detail',
                                       kwargs={'pk': self.mine.pk})).content.decode()
        self.assertNotIn('09120000000', body)
        self.assertNotIn('مال من', body)

    def test_there_is_no_separate_lead_list_any_more(self):
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('leads:list')

    def test_marketer_sees_only_their_own_qr(self):
        mine = LeadSource.objects.create(name='qr-mine', marketer=self.a)
        other = LeadSource.objects.create(name='qr-other', marketer=self.boss)
        public = LeadSource.objects.create(name='qr-public')
        self.client.force_login(self.a)
        response = self.client.get(reverse('leads:sources'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['sources']), [mine])
        self.assertNotContains(response, other.token)
        self.assertNotContains(response, public.token)
        self.assertNotContains(response, 'QR جدید')

    def test_management_sees_every_qr(self):
        LeadSource.objects.create(name='qr-public')
        self.client.force_login(self.boss)
        response = self.client.get(reverse('leads:sources'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'QR جدید')
        self.assertTrue(any(s.name == 'qr-public' for s in response.context['sources']))


class MarketerKeepsTheirLeadTests(TestCase):
    """A marketer must be able to follow and annotate what they captured.

    Both halves of this went missing when exhibition leads were folded into
    the ordinary request pipeline: the screen holding the marketer's own read
    of a lead was removed and never replaced, and scoping purely by department
    meant that referring a lead onward made it disappear from its captor.
    """

    def setUp(self):
        self.marketer = User.objects.create_user(
            username='mk_own', password='Zx9!kQ2mVr7t', role='marketing')
        self.other = User.objects.create_user(
            username='mk_other', password='Zx9!kQ2mVr7t', role='marketing')
        self.boss = User.objects.create_user(
            username='mk_boss', password='Zx9!kQ2mVr7t',
            is_superuser=True, is_staff=True)
        source = LeadSource.objects.create(
            name='غرفه', marketer=self.marketer, event_name='EXPO')
        self.client.post(reverse('leads:capture', kwargs={'token': source.token}), {
            'full_name': 'مهدی', 'mobile': '09120001234', 'company': 'نمونه',
            'goals': ['sell_power'], 'timeline': 'lt_1m', 'contact_method': 'call',
            'province': 'تهران', 'city': 'تهران'})
        self.req = Request.objects.get()
        self.lead = Lead.objects.get()

    def _visible_to(self, user):
        return repositories.scope_requests_by_department(
            user, Request.objects.all()).filter(pk=self.req.pk).exists()

    def test_sees_their_lead_at_every_stage(self):
        for dept in (Request.Department.MARKETING, Request.Department.SALES,
                     Request.Department.TECHNICAL, Request.Department.DONE):
            Request.objects.filter(pk=self.req.pk).update(department=dept)
            self.assertTrue(self._visible_to(self.marketer),
                            f'marketer lost their own lead in {dept}')

    def test_another_marketer_still_cannot_see_it(self):
        self.assertFalse(self._visible_to(self.other))
        Request.objects.filter(pk=self.req.pk).update(
            department=Request.Department.SALES)
        self.assertFalse(self._visible_to(self.other))

    def test_can_save_their_analysis(self):
        self.client.force_login(self.marketer)
        resp = self.client.post(
            reverse('requests:admin-lead-note', args=[self.req.id]),
            {'temperature': 'hot', 'next_action': 'تماس تا پنج‌شنبه',
             'decision_role': 'مدیر فنی', 'marketer_impression': 'بودجه دارد',
             'notes': 'در غرفه خیلی علاقه‌مند بود'})
        self.assertEqual(resp.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.temperature, 'hot')
        self.assertEqual(self.lead.next_action, 'تماس تا پنج‌شنبه')
        self.assertEqual(self.lead.marketer_impression, 'بودجه دارد')

    def test_can_still_save_after_referring_to_sales(self):
        Request.objects.filter(pk=self.req.pk).update(
            department=Request.Department.SALES)
        self.client.force_login(self.marketer)
        self.client.post(reverse('requests:admin-lead-note', args=[self.req.id]),
                         {'notes': 'بعد از ارجاع هم یادداشت می‌گذارم'})
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.notes, 'بعد از ارجاع هم یادداشت می‌گذارم')

    def test_another_marketer_cannot_write_on_it(self):
        self.client.force_login(self.other)
        self.client.post(reverse('requests:admin-lead-note', args=[self.req.id]),
                         {'notes': 'دست‌درازی'})
        self.lead.refresh_from_db()
        self.assertNotEqual(self.lead.notes, 'دست‌درازی')

    def test_management_can_write_on_it(self):
        self.client.force_login(self.boss)
        self.client.post(reverse('requests:admin-lead-note', args=[self.req.id]),
                         {'notes': 'بازبینی مدیر'})
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.notes, 'بازبینی مدیر')

    def test_the_form_is_on_the_detail_page_for_its_marketer(self):
        self.client.force_login(self.marketer)
        html = self.client.get(
            reverse('requests:admin-detail', args=[self.req.id])).content.decode()
        self.assertIn('name="marketer_impression"', html)
        self.assertIn('name="temperature"', html)

    def test_sales_reads_it_but_gets_no_form(self):
        rep = User.objects.create_user(
            username='mk_sales', password='Zx9!kQ2mVr7t', role='sales')
        self.lead.marketer_impression = 'بودجه دارد'
        self.lead.save()
        self.client.force_login(rep)
        html = self.client.get(
            reverse('requests:admin-detail', args=[self.req.id])).content.decode()
        self.assertIn('بودجه دارد', html)
        self.assertNotIn('name="marketer_impression"', html)

    def test_a_website_lead_has_no_analysis_form(self):
        """Only exhibition leads carry a Lead row; the endpoint must say so."""
        from apps.requests.services import lifecycle
        web = lifecycle.create_request(
            full_name='از سایت', mobile='09120005555', province='تهران')
        self.client.force_login(self.marketer)
        resp = self.client.post(
            reverse('requests:admin-lead-note', args=[web.id]), {'notes': 'x'})
        self.assertEqual(resp.status_code, 302)


class DuplicateCaptureTests(CaptureFlowTests):
    def test_second_tap_reuses_the_same_request(self):
        first = self._capture()
        second = self._capture()
        self.assertEqual(Request.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(first['Location'], second['Location'])

    def test_other_mobile_is_a_new_request(self):
        self._capture()
        self._capture(mobile='09121111111')
        self.assertEqual(Request.objects.count(), 2)
