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
        'user_type': 'individual', 'full_name': 'علی', 'project_type': 'residential',
        'needs_financial_consult': 'False', 'province': 'تهران', 'city': 'تهران',
        'install_address': '', 'area_m2': '120', 'install_location': 'rooftop',
        'building_type': 'villa', 'has_shading': 'False', 'description': 'x',
        'ownership_type': 'dedicated', 'grid_distance_m': '50', 'storage_interest': 'no',
        'bill_id': '1234567890123', 'mobile': mobile, 'national_id': '1234567890',
        'accepted_terms': 'on',
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
        resp = self.client.post(reverse('requests:admin-status', args=[req.id]), {'status': 'cancelled'}, **HOST)
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
        # Shahkar (mock) ran automatically on submit.
        self.assertTrue(req.identity_verified)
        self.assertEqual(req.national_id, '1234567890')

        code = OtpVerification.objects.filter(mobile=mobile, is_used=False).latest('created_at').code
        resp = self.client.post(reverse('requests:verify'), {'code': code}, **HOST)
        req.refresh_from_db()
        self.assertIsNotNone(req.user)
        self.assertTrue(User.objects.filter(username=mobile).exists())

    def test_submit_blocked_on_identity_mismatch(self):
        from apps.core.models import SystemParameter
        SystemParameter.objects.update_or_create(key='shahkar_mock_result', defaults={'value': 'false'})
        mobile = '09120000024'
        resp = self.client.post(reverse('requests:submit'), eval_post(mobile), **HOST)
        self.assertEqual(resp.status_code, 200)  # re-rendered with an error, not redirected
        self.assertFalse(Request.objects.filter(mobile=mobile).exists())

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
