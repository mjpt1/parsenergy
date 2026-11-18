from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Permission, Role, RolePermission, UserRole
from apps.requests.models import OtpVerification, Request
from apps.requests.services import lifecycle, offers

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}


def eval_post(mobile, **over):
    """Valid POST payload for the full evaluation form."""
    data = {
        'request_type': 'dedicated',
        'user_type': 'individual', 'full_name': 'علی', 'project_type': 'residential',
        'needs_financial_consult': 'False', 'province': 'تهران', 'city': 'تهران',
        'install_address': '', 'area_m2': '120', 'install_location': 'rooftop',
        'building_type': 'villa', 'has_shading': 'False', 'description': 'x',
        'ownership_type': 'dedicated', 'grid_distance_m': '50', 'storage_interest': 'no',
        'area_range': '100_500', 'shade_status': 'no',
        'bill_id': '1234567890123', 'mobile': mobile, 'national_id': '1234567890',
        'accepted_terms': 'on', 'contact_method': 'call',
    }
    data.update(over)
    return data


def grant_manage(user):
    perm, _ = Permission.objects.get_or_create(code='requests.manage')
    role, _ = Role.objects.get_or_create(name='ReqMgr')
    RolePermission.objects.get_or_create(role=role, permission=perm)
    UserRole.objects.get_or_create(user=user, role=role)


class AdminAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin1', password='p', is_superuser=True, is_staff=True)
        self.manager = User.objects.create_user(username='mgr', password='p')
        grant_manage(self.manager)
        self.plain = User.objects.create_user(username='plain', password='p')

    def test_superuser_can_open_admin_list(self):
        self.client.login(username='admin1', password='p')
        self.assertEqual(self.client.get(reverse('requests:admin-list'), **HOST).status_code, 200)

    def test_permission_holder_can_open_admin_list(self):
        self.client.login(username='mgr', password='p')
        self.assertEqual(self.client.get(reverse('requests:admin-list'), **HOST).status_code, 200)

    def test_plain_user_forbidden(self):
        self.client.login(username='plain', password='p')
        self.assertEqual(self.client.get(reverse('requests:admin-list'), **HOST).status_code, 403)

    def test_admin_can_add_offer(self):
        req = lifecycle.create_request(full_name='ت', mobile='09120000010', province='تهران')
        lifecycle.refer_marketing_to_sales(req, actor=self.admin)
        lifecycle.refer_sales_to_technical(req, actor=self.admin, priority='high')
        self.client.login(username='admin1', password='p')
        resp = self.client.post(
            reverse('requests:admin-offer-add', args=[req.id]),
            {'title': 'A', 'amount': '5000'}, **HOST,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(req.offers.count(), 1)

    def test_admin_issue_contract_from_offer(self):
        from apps.requests.models import RequestContract
        req = lifecycle.create_request(full_name='ت', mobile='09120000012', province='تهران')
        offer = offers.add_offer(request=req, title='A', amount=1000)  # -> offered
        self.client.login(username='admin1', password='p')
        resp = self.client.post(reverse('requests:admin-offer-issue-contract', args=[offer.id]), {}, **HOST)
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.CONTRACT_GENERATED)
        self.assertTrue(RequestContract.objects.filter(request=req).exists())

    def test_admin_cancel_request(self):
        """Regression: status-change (cancel) must not 500 on a non-ASCII SMS body."""
        req = lifecycle.create_request(full_name='ت', mobile='09120000010', province='تهران')
        offers.add_offer(request=req, title='A', amount=1000)
        self.client.login(username='admin1', password='p')
        resp = self.client.post(reverse('requests:admin-status', args=[req.id]), {'status': 'cancelled', 'reason': 'budget'}, **HOST)
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.CANCELLED)

    def test_admin_cannot_force_forward_status(self):
        req = lifecycle.create_request(full_name='ت', mobile='09120000011', province='تهران')
        offers.add_offer(request=req, title='A', amount=1000)  # -> offered
        self.client.login(username='admin1', password='p')
        resp = self.client.post(reverse('requests:admin-status', args=[req.id]), {'status': 'contract_generated'}, **HOST)
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.OFFERED)  # unchanged


class UserFlowTests(TestCase):
    def test_submit_then_otp_register_attaches_request(self):
        mobile = '09120000020'
        # anonymous submit
        resp = self.client.post(reverse('requests:submit'), eval_post(mobile), **HOST)
        self.assertRedirects(resp, reverse('requests:verify'), fetch_redirect_response=False)
        req = Request.objects.get(mobile=mobile)
        self.assertIsNone(req.user)
        # Identity is left for the contract step.
        self.assertFalse(req.identity_verified)
        self.assertEqual(req.national_id, '')

        code = OtpVerification.objects.filter(mobile=mobile, is_used=False).latest('created_at').code
        resp = self.client.post(reverse('requests:verify'), {'code': code}, **HOST)
        req.refresh_from_db()
        self.assertIsNotNone(req.user)
        self.assertTrue(User.objects.filter(username=mobile).exists())

    def test_submit_does_not_depend_on_identity_service(self):
        from apps.core.models import SystemParameter
        SystemParameter.objects.update_or_create(key='shahkar_mock_result', defaults={'value': 'false'})
        mobile = '09120000024'
        resp = self.client.post(reverse('requests:submit'), eval_post(mobile), **HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Request.objects.filter(mobile=mobile, identity_verified=False).exists())

    def test_duplicate_mobile_login_path(self):
        mobile = '09120000021'
        User.objects.create_user(username=mobile, password='p', phone_number=mobile)
        # submitting with an existing mobile issues a LOGIN otp (no duplicate account)
        self.client.post(reverse('requests:submit'), eval_post(mobile, full_name='x'), **HOST)
        otp = OtpVerification.objects.filter(mobile=mobile).latest('created_at')
        self.assertEqual(otp.purpose, OtpVerification.Purpose.LOGIN)
        self.assertEqual(User.objects.filter(username=mobile).count(), 1)

    def test_select_offer_creates_contract_via_http(self):
        """Regression: the select -> generate-contract -> contract page path must
        not 500 (e.g. from SMS console output) and must render the contract."""
        from apps.requests.models import RequestContract
        admin = User.objects.create_user(username='admin_sel', password='p', is_superuser=True)
        cust = User.objects.create_user(username='09120000040', password='p', phone_number='09120000040')
        req = lifecycle.create_request(full_name='x', mobile='09120000040', province='ت', user=cust)
        offer = offers.add_offer(request=req, title='A', amount=1000, created_by=admin)

        self.client.login(username='09120000040', password='p')
        resp = self.client.post(reverse('requests:select-offer', args=[req.id]), {'offer_id': offer.id}, **HOST)
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse('requests:contract', args=[req.id]), fetch_redirect_response=False)
        self.assertTrue(RequestContract.objects.filter(request=req).exists())
        self.assertEqual(self.client.get(reverse('requests:contract', args=[req.id]), **HOST).status_code, 200)

    def test_my_list_scoped_to_user(self):
        u1 = User.objects.create_user(username='u1', password='p')
        u2 = User.objects.create_user(username='u2', password='p')
        lifecycle.create_request(full_name='a', mobile='09120000022', province='ت', user=u1)
        lifecycle.create_request(full_name='b', mobile='09120000023', province='ت', user=u2)
        self.client.login(username='u1', password='p')
        resp = self.client.get(reverse('requests:my-list'), **HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context['requests']), list(Request.objects.filter(user=u1)))


class TechnicalPrivacyTests(TestCase):
    def setUp(self):
        self.tech = User.objects.create_user(
            username='tech1', password='p', role=User.Role.TECHNICAL, is_staff=True)
        self.sales = User.objects.create_user(
            username='sales1', password='p', role=User.Role.SALES, is_staff=True)
        self.req = lifecycle.create_request(
            full_name='مشتری محرمانه', mobile='09121112233', province='تهران',
            city='تهران', description='پروژه تست')
        self.req.install_address = 'خیابان آزادی پلاک ۱'
        self.req.national_id = '0012345678'
        self.req.investment_range = Request.InvestmentRange.OVER_5B
        self.req.needs_financial_consult = True
        self.req.latitude = '35.689200'
        self.req.longitude = '51.389000'
        self.req.bill_id = '9876543210987'
        self.req.department = Request.Department.TECHNICAL
        self.req.save()

    def test_technical_detail_hides_identity_keeps_address_and_map(self):
        self.client.login(username='tech1', password='p')
        resp = self.client.get(reverse('requests:admin-detail', args=[self.req.id]), **HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['hide_customer_identity'])
        body = resp.content.decode('utf-8')
        self.assertNotIn('مشتری محرمانه', body)
        self.assertNotIn('09121112233', body)
        self.assertNotIn('0012345678', body)
        self.assertNotIn('بیش از ۵ میلیارد', body)
        self.assertIn('خیابان آزادی پلاک ۱', body)
        self.assertIn('adminLocationMap', body)
        self.assertIn('9876543210987', body)

    def test_sales_detail_still_shows_identity(self):
        self.req.department = Request.Department.SALES
        self.req.save(update_fields=['department'])
        self.client.login(username='sales1', password='p')
        resp = self.client.get(reverse('requests:admin-detail', args=[self.req.id]), **HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['hide_customer_identity'])
        body = resp.content.decode('utf-8')
        self.assertIn('مشتری محرمانه', body)
        self.assertIn('09121112233', body)

    def test_technical_list_hides_name_and_mobile(self):
        self.client.login(username='tech1', password='p')
        resp = self.client.get(reverse('requests:admin-list'), **HOST)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertNotIn('مشتری محرمانه', body)
        self.assertNotIn('09121112233', body)


class ApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='apiuser', password='p')

    def test_create_and_list_scoped(self):
        self.client.login(username='apiuser', password='p')
        resp = self.client.post('/api/requests/', {
            'full_name': 'API', 'mobile': '09120000030', 'province': 'تهران',
        }, content_type='application/json', **HOST)
        self.assertEqual(resp.status_code, 201)
        listing = self.client.get('/api/requests/', **HOST)
        self.assertEqual(listing.json()['count'], 1)

    def test_otp_register_returns_token(self):
        mobile = '09120000031'
        self.assertEqual(
            self.client.post('/api/request-otp/request/', {'mobile': mobile, 'purpose': 'register'},
                             content_type='application/json', **HOST).status_code, 200)
        code = OtpVerification.objects.filter(mobile=mobile, purpose='register').latest('created_at').code
        resp = self.client.post('/api/request-otp/verify/', {'mobile': mobile, 'code': code, 'purpose': 'register'},
                                content_type='application/json', **HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.json())


class WebsiteLeadWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='adm', password='p', role=User.Role.ADMIN, is_staff=True, is_superuser=True)
        self.mkt = User.objects.create_user(
            username='mkt', password='p', role=User.Role.MARKETING, is_staff=True)
        self.sales = User.objects.create_user(
            username='sls', password='p', role=User.Role.SALES, is_staff=True)
        self.tech = User.objects.create_user(
            username='tch', password='p', role=User.Role.TECHNICAL, is_staff=True)
        self.ops = User.objects.create_user(
            username='ops', password='p', role=User.Role.OPERATIONS, is_staff=True)

    def test_full_pipeline_marketing_to_crm(self):
        req = lifecycle.create_request(
            full_name='لید تست', mobile='09120000111', province='تهران',
            lead_source='google', campaign_name='Summer2026', utm_medium='cpc')
        self.assertEqual(req.department, Request.Department.MARKETING)

        lifecycle.refer_marketing_to_sales(req, actor=self.mkt)
        req.refresh_from_db()
        self.assertEqual(req.department, Request.Department.SALES)
        self.assertEqual(req.sales_phase, Request.SalesPhase.QUALIFICATION)

        lifecycle.refer_sales_to_technical(req, actor=self.sales, priority='high')
        req.refresh_from_db()
        self.assertEqual(req.department, Request.Department.TECHNICAL)
        self.assertEqual(req.priority, 'high')

        offers.add_offer(request=req, title='پیشنهاد ۱', amount=10_000_000, created_by=self.tech)
        lifecycle.refer_to_sales(req, actor=self.tech, note='ظرفیت ۱۰ کیلووات')
        req.refresh_from_db()
        self.assertEqual(req.department, Request.Department.SALES)
        self.assertEqual(req.sales_phase, Request.SalesPhase.NEGOTIATION)

        lifecycle.close_by_sales(req, actor=self.sales)
        req.refresh_from_db()
        self.assertEqual(req.department, Request.Department.DONE)
        self.assertTrue(req.crm_transferred)
        self.assertIsNotNone(req.crm_transferred_at)

    def test_hold_and_close_lost(self):
        req = lifecycle.create_request(full_name='هولد', mobile='09120000112', province='اصفهان')
        lifecycle.refer_marketing_to_sales(req, actor=self.mkt)
        lifecycle.hold_request(req, actor=self.sales)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.HOLD)

        req2 = lifecycle.create_request(full_name='ازدست', mobile='09120000113', province='شیراز')
        lifecycle.refer_marketing_to_sales(req2, actor=self.mkt)
        lifecycle.close_lost(req2, actor=self.sales)
        req2.refresh_from_db()
        self.assertEqual(req2.status, Request.Status.CLOSED)
        self.assertEqual(req2.department, Request.Department.DONE)

    def test_marketing_and_ops_can_open_dashboard(self):
        # Each role lands on its own dashboard (admin/technical redirect to /dashboard/).
        for username in ('mkt', 'ops', 'sls', 'tch', 'adm'):
            self.client.login(username=username, password='p')
            resp = self.client.get(reverse('requests:admin-dashboard'), follow=True, **HOST)
            self.assertEqual(resp.status_code, 200, username)
            if username == 'adm':
                self.assertContains(resp, 'مدیرکل')
            elif username == 'tch':
                self.assertContains(resp, 'داشبورد فنی')
            elif username == 'mkt':
                self.assertContains(resp, 'توسعه بازار')
            elif username == 'sls':
                self.assertContains(resp, 'داشبورد فروش')
            elif username == 'ops':
                self.assertContains(resp, 'عملیات')

    def test_search_filters_identity_for_sales(self):
        lifecycle.create_request(full_name='جستجوگر', mobile='09129998877', province='تهران')
        self.client.login(username='sls', password='p')
        # Move to sales so sales can see it
        req = Request.objects.get(mobile='09129998877')
        req.department = Request.Department.SALES
        req.sales_phase = Request.SalesPhase.QUALIFICATION
        req.save(update_fields=['department', 'sales_phase'])
        resp = self.client.get(reverse('requests:admin-list'), {'q': '09129998877'}, **HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'جستجوگر')

    def test_technical_cannot_search_by_mobile(self):
        req = lifecycle.create_request(
            full_name='مخفی', mobile='09127776655', province='تهران',
            install_address='آدرس فنی')
        req.department = Request.Department.TECHNICAL
        req.save(update_fields=['department'])
        self.client.login(username='tch', password='p')
        resp = self.client.get(reverse('requests:admin-list'), {'q': '09127776655'}, **HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'مخفی')


class SalesCannotActWhileMarketingOwnsLeadTests(TestCase):
    """Sales watches a new lead from the start but may not act on it.

    The pipeline is marketing → sales → technical. Most sales actions are
    gated on `department == SALES` and so were already safe; cancelling,
    unlocking customer edits, and closing-as-lost were not.
    """

    def setUp(self):
        self.sales = User.objects.create_user(username='s_guard', password='p', role='sales')
        self.marketer = User.objects.create_user(username='m_guard', password='p', role='marketing')
        self.req = lifecycle.create_request(
            full_name='در صف بازاریابی', mobile='09120007001', province='تهران')
        self.assertEqual(self.req.department, Request.Department.MARKETING)

    def test_sales_sees_the_lead_in_the_list(self):
        self.client.force_login(self.sales)
        response = self.client.get(reverse('requests:admin-list'), **HOST)
        self.assertContains(response, 'در انتظار بازاریابی')

    def test_sales_cannot_close_marketing_lead_as_lost(self):
        self.client.force_login(self.sales)
        self.client.post(reverse('requests:admin-close-lost', args=[self.req.id]), **HOST)
        self.req.refresh_from_db()
        self.assertEqual(self.req.department, Request.Department.MARKETING)

    def test_sales_cannot_unlock_edits_on_marketing_lead(self):
        self.client.force_login(self.sales)
        self.client.post(reverse('requests:admin-toggle-edit', args=[self.req.id]), **HOST)
        self.req.refresh_from_db()
        self.assertFalse(self.req.edit_unlocked)

    def test_sales_cannot_cancel_marketing_lead(self):
        self.client.force_login(self.sales)
        self.client.post(reverse('requests:admin-status', args=[self.req.id]),
                         {'status': Request.Status.CANCELLED}, **HOST)
        self.req.refresh_from_db()
        self.assertNotEqual(self.req.status, Request.Status.CANCELLED)

    def test_management_can_still_drop_a_junk_lead(self):
        """The guard must not disarm management, which oversees every stage.

        (Marketing itself cannot close-lost — the view has always required
        sales or management. That is pre-existing and untouched here.)
        """
        boss = User.objects.create_user(
            username='boss_guard', password='p', is_superuser=True, is_staff=True)
        self.client.force_login(boss)
        self.client.post(reverse('requests:admin-close-lost', args=[self.req.id]), {'reason': 'duplicate'}, **HOST)
        self.req.refresh_from_db()
        self.assertEqual(self.req.department, Request.Department.DONE)

    def test_sales_can_act_once_marketing_refers(self):
        lifecycle.refer_marketing_to_sales(self.req, actor=self.marketer)
        self.client.force_login(self.sales)
        self.client.post(reverse('requests:admin-close-lost', args=[self.req.id]), {'reason': 'budget'}, **HOST)
        self.req.refresh_from_db()
        self.assertEqual(self.req.department, Request.Department.DONE)


class CustomerEditTests(TestCase):
    """Editing a request must not 500 on the empty hidden attribution inputs,
    and must keep the attribution captured on the first visit."""

    def test_edit_keeps_attribution_and_saves(self):
        from django.utils import timezone
        user = User.objects.create_user(username='09121112233', password='p')
        req = lifecycle.create_request(
            full_name='علی', mobile='09121112233', province='تهران', city='تهران', user=user,
            utm_source='instagram', first_visit_at=timezone.now(), edit_unlocked=True)
        self.client.login(username='09121112233', password='p')
        data = eval_post('09121112233', full_name='علی رضایی', first_visit_at='', utm_source='')
        resp = self.client.post(reverse('requests:my-edit', args=[req.id]), data, **HOST)
        self.assertEqual(resp.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.full_name, 'علی رضایی')
        self.assertEqual(req.utm_source, 'instagram')
        self.assertIsNotNone(req.first_visit_at)
