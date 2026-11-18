"""Two login doors, and nobody ending up behind the wrong one.

Staff sign in with a username and password; customers with a mobile and a
texted code. Before this, the staff door was not linked from anywhere public,
so employees used the customer one — which silently created a second, customer
account for them and dropped them in the customer portal.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.requests.models import OtpVerification
from apps.requests.services import otp as otp_service

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}


class BothDoorsAreVisibleTests(TestCase):
    def test_public_pages_link_to_the_staff_door(self):
        for name in ('accounts:login', 'requests:otp-login', 'requests:submit'):
            html = self.client.get(reverse(name), follow=True, **HOST).content.decode()
            self.assertIn(reverse('accounts:login'), html, name)

    def test_public_pages_link_to_the_customer_door(self):
        for name in ('accounts:login', 'requests:otp-login', 'requests:submit'):
            html = self.client.get(reverse(name), follow=True, **HOST).content.decode()
            self.assertIn(reverse('requests:otp-login'), html, name)

    def test_staff_login_page_names_itself(self):
        html = self.client.get(reverse('accounts:login'), **HOST).content.decode()
        self.assertIn('ورود پرسنل', html)
        # It is not a customer account page, so it must not wear the account tabs.
        self.assertNotIn(reverse('requests:my-tickets'), html)


class StaffSignInWithTheirOwnMobileTests(TestCase):
    """Staff may use the texted-code door too — as themselves."""

    def setUp(self):
        self.rep = User.objects.create_user(
            username='door_sales', password='Zx9!kQ2mVr7t', role='sales')
        self.rep.phone_number = '09121110000'
        self.rep.save()

    def _verify(self, mobile):
        self.client.post(reverse('requests:otp-login'), {'mobile': mobile}, **HOST)
        code = OtpVerification.objects.filter(mobile=mobile).latest('id').code
        return self.client.post(reverse('requests:verify'), {'code': code},
                                follow=True, **HOST)

    def test_their_mobile_is_recognised_as_a_login(self):
        resp = self.client.post(reverse('requests:otp-login'),
                                {'mobile': '09121110000'}, **HOST)
        self.assertRedirects(resp, reverse('requests:verify'), fetch_redirect_response=False)
        self.assertEqual(
            OtpVerification.objects.filter(mobile='09121110000').latest('id').purpose,
            OtpVerification.Purpose.LOGIN)

    def test_signs_into_their_real_account_not_a_new_one(self):
        self._verify('09121110000')
        self.assertFalse(User.objects.filter(username='09121110000').exists())
        self.assertEqual(User.objects.filter(phone_number='09121110000').count(), 1)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.rep.pk)

    def test_lands_on_the_staff_dashboard(self):
        resp = self._verify('09121110000')
        self.assertEqual(resp.redirect_chain[-1][0], reverse('dashboard'))

    def test_does_not_inherit_a_customer_request(self):
        """Anonymous requests with that mobile belong to customers, not staff."""
        from apps.requests.services import lifecycle
        req = lifecycle.create_request(
            full_name='مشتری', mobile='09121110000', province='تهران')
        self._verify('09121110000')
        req.refresh_from_db()
        self.assertIsNone(req.user)

    def test_a_customer_mobile_still_works(self):
        resp = self.client.post(reverse('requests:otp-login'),
                                {'mobile': '09129998888'}, **HOST)
        self.assertRedirects(resp, reverse('requests:verify'), fetch_redirect_response=False)


class StaffMobileIsRequiredTests(TestCase):
    """An account with no mobile cannot use the texted-code door at all."""

    def setUp(self):
        self.boss = User.objects.create_user(
            username='door_boss', password='Zx9!kQ2mVr7t',
            is_superuser=True, is_staff=True)
        self.client.force_login(self.boss)

    def _create(self, **over):
        data = {'username': 'newstaff', 'first_name': 'علی', 'last_name': 'رضایی',
                'phone_number': '09121234567', 'role': 'sales',
                'password1': 'Zx9!kQ2mVr7t', 'password2': 'Zx9!kQ2mVr7t'}
        data.update(over)
        return self.client.post(reverse('accounts:staff-manage-create'), data, **HOST)

    def test_cannot_create_staff_without_a_mobile(self):
        self._create(phone_number='')
        self.assertFalse(User.objects.filter(username='newstaff').exists())

    def test_creates_with_a_mobile(self):
        self._create()
        self.assertEqual(
            User.objects.get(username='newstaff').phone_number, '09121234567')

    def test_persian_digits_and_plus98_are_normalised(self):
        self._create(phone_number='+98 912 123 4568')
        self.assertEqual(
            User.objects.get(username='newstaff').phone_number, '09121234568')

    def test_a_mobile_cannot_be_shared_by_two_accounts(self):
        self._create()
        self._create(username='newstaff2')
        self.assertFalse(User.objects.filter(username='newstaff2').exists())


class OtpLandingRespectsRoleTests(TestCase):
    """Whoever verifies an OTP lands where their role belongs, not always
    in the customer request list."""

    def _verify_as(self, mobile):
        self.client.post(reverse('requests:otp-login'), {'mobile': mobile}, **HOST)
        code = OtpVerification.objects.filter(mobile=mobile).latest('id').code
        return self.client.post(reverse('requests:verify'), {'code': code},
                                follow=True, **HOST)

    def test_staff_account_lands_on_the_dashboard(self):
        # A staff account whose username *is* their mobile can still sign in
        # here; it must not drop them into the customer area.
        User.objects.create_user(username='09121112222', password='Zx9!kQ2mVr7t',
                                 role='marketing')
        resp = self._verify_as('09121112222')
        self.assertEqual(resp.redirect_chain[-1][0], reverse('dashboard'))

    def test_customer_lands_in_their_request_list(self):
        resp = self._verify_as('09123334444')
        self.assertEqual(resp.redirect_chain[-1][0], reverse('requests:my-list'))
        self.assertEqual(
            User.objects.get(username='09123334444').role, User.Role.CUSTOMER)
