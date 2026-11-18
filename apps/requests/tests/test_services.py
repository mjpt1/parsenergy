import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.core.models import AuditLog
from apps.requests.models import (
    OtpVerification,
    Request,
    RequestContract,
    RequestMessageLog,
    RequestPayment,
)
from apps.requests.services import contracts, lifecycle, offers
from apps.requests.services import otp as otp_service
from apps.requests.services import payments

User = get_user_model()
MOBILE = '09120000001'


def _approved_contract(mobile=MOBILE):
    """Helper: build a request up to an approved contract; return (req, offer, contract)."""
    req = lifecycle.create_request(full_name='ت', mobile=mobile, province='تهران')
    # Identity is verified before a contract can be approved / paid.
    req.national_id = '1234567890'
    req.identity_verified = True
    req.identity_verified_at = timezone.now()
    req.save(update_fields=['national_id', 'identity_verified', 'identity_verified_at'])
    offer = offers.add_offer(request=req, title='A', amount=1000)
    contract = offers.select_offer(request=req, offer=offer)
    contracts.request_approval_otp(contract)
    code = OtpVerification.objects.filter(
        mobile=mobile, purpose=OtpVerification.Purpose.CONTRACT_APPROVAL, is_used=False,
    ).latest('created_at').code
    contracts.approve_with_otp(contract=contract, code=code)
    req.refresh_from_db()
    return req, offer, contract


class LifecycleTests(TestCase):
    def test_create_sets_new_and_writes_audit(self):
        req = lifecycle.create_request(full_name='ع', mobile=MOBILE, province='تهران')
        self.assertEqual(req.status, Request.Status.NEW)
        self.assertTrue(AuditLog.objects.filter(action='request.created', target_id=str(req.id)).exists())

    def test_valid_transition(self):
        req = lifecycle.create_request(full_name='ع', mobile=MOBILE, province='تهران')
        lifecycle.transition(req, Request.Status.OFFERED)
        self.assertEqual(req.status, Request.Status.OFFERED)

    def test_invalid_transition_raises(self):
        req = lifecycle.create_request(full_name='ع', mobile=MOBILE, province='تهران')
        with self.assertRaises(lifecycle.TransitionError):
            lifecycle.transition(req, Request.Status.PAID)


class OfferTests(TestCase):
    def setUp(self):
        self.req = lifecycle.create_request(full_name='ع', mobile=MOBILE, province='تهران')

    def test_first_offer_moves_to_offered(self):
        offers.add_offer(request=self.req, title='A', amount=1000)
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, Request.Status.OFFERED)

    def test_max_three_offers(self):
        for i in range(3):
            offers.add_offer(request=self.req, title=f'O{i}', amount=1000)
        with self.assertRaises(offers.OfferError):
            offers.add_offer(request=self.req, title='X', amount=1)

    def test_toggle_active(self):
        offer = offers.add_offer(request=self.req, title='A', amount=1000)
        offers.toggle_active(offer)
        offer.refresh_from_db()
        self.assertFalse(offer.is_active)

    def test_expired_offer_not_payable(self):
        offer = offers.add_offer(
            request=self.req, title='A', amount=1000,
            valid_until=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(offer.is_payable)

    def test_select_inactive_offer_rejected(self):
        offer = offers.add_offer(request=self.req, title='A', amount=1000)
        offers.toggle_active(offer)
        with self.assertRaises(offers.OfferError):
            offers.select_offer(request=self.req, offer=offer)


class OtpTests(TestCase):
    def test_issue_and_verify(self):
        otp = otp_service.issue(mobile=MOBILE, purpose=OtpVerification.Purpose.LOGIN)
        verified = otp_service.verify(mobile=MOBILE, code=otp.code, purpose=OtpVerification.Purpose.LOGIN)
        self.assertTrue(verified.is_used)

    def test_wrong_code_rejected(self):
        otp_service.issue(mobile=MOBILE, purpose=OtpVerification.Purpose.LOGIN)
        with self.assertRaises(otp_service.OtpError):
            otp_service.verify(mobile=MOBILE, code='00000', purpose=OtpVerification.Purpose.LOGIN)

    def test_expired_code_rejected(self):
        otp = otp_service.issue(mobile=MOBILE, purpose=OtpVerification.Purpose.LOGIN)
        otp.expires_at = timezone.now() - timedelta(minutes=1)
        otp.save(update_fields=['expires_at'])
        with self.assertRaises(otp_service.OtpError):
            otp_service.verify(mobile=MOBILE, code=otp.code, purpose=OtpVerification.Purpose.LOGIN)

    def test_issue_logs_sms(self):
        otp_service.issue(mobile=MOBILE, purpose=OtpVerification.Purpose.LOGIN)
        log = RequestMessageLog.objects.filter(mobile=MOBILE, message_type='otp').latest('created_at')
        self.assertEqual(log.status, RequestMessageLog.Status.SENT)


class ContractTests(TestCase):
    def test_generate_and_approve(self):
        req, offer, contract = _approved_contract()
        self.assertEqual(contract.status, RequestContract.Status.APPROVED)
        self.assertEqual(req.status, Request.Status.CONTRACT_APPROVED)

    def test_approve_wrong_code(self):
        req = lifecycle.create_request(full_name='ت', mobile=MOBILE, province='تهران')
        offer = offers.add_offer(request=req, title='A', amount=1000)
        contract = offers.select_offer(request=req, offer=offer)
        contracts.request_approval_otp(contract)
        with self.assertRaises(otp_service.OtpError):
            contracts.approve_with_otp(contract=contract, code='00000')


class PaymentTests(TestCase):
    def test_payment_requires_approved_contract(self):
        req = lifecycle.create_request(full_name='ت', mobile=MOBILE, province='تهران')
        offer = offers.add_offer(request=req, title='A', amount=1000)
        offers.select_offer(request=req, offer=offer)  # contract generated, not approved
        with self.assertRaises(payments.PaymentError):
            payments.create_for_offer(request=req, offer=offer)

    def test_full_payment_flow(self):
        req, offer, _ = _approved_contract()
        payment, url = payments.create_for_offer(request=req, offer=offer)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.AWAITING_PAYMENT)
        self.assertIn(str(payment.token), url)

        paid = payments.handle_callback(token=payment.token, data={'result': 'success'})
        req.refresh_from_db()
        self.assertEqual(paid.status, RequestPayment.Status.PAID)
        self.assertEqual(req.status, Request.Status.PAID)
        self.assertTrue(
            RequestMessageLog.objects.filter(mobile=MOBILE, message_type='payment_success').exists()
        )

    def test_callback_is_idempotent(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        payments.handle_callback(token=payment.token, data={'result': 'success'})
        again = payments.handle_callback(token=payment.token, data={'result': 'success'})
        self.assertEqual(again.status, RequestPayment.Status.PAID)

    def test_cancelled_callback_marks_failed(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        result = payments.handle_callback(token=payment.token, data={'result': 'cancel'})
        self.assertEqual(result.status, RequestPayment.Status.FAILED)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.AWAITING_PAYMENT)

    def test_empty_callback_does_not_mark_paid(self):
        """A callback carrying no gateway result must never settle a payment.

        Guards the regression where the view defaulted a bare GET to 'success',
        letting anyone mark their own request paid without paying.
        """
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        result = payments.handle_callback(token=payment.token, data={})
        self.assertNotEqual(result.status, RequestPayment.Status.PAID)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.Status.AWAITING_PAYMENT)


class PaymentCallbackViewTests(TestCase):
    """The HTTP surface of the callback — the part an attacker can reach."""

    def _paid_ready(self):
        req, offer, _ = _approved_contract()
        user = User.objects.create_user(username=MOBILE, password='Zx9!kQ2mVr7t')
        req.user = user
        req.save(update_fields=['user'])
        payment, _url = payments.create_for_offer(request=req, offer=offer)
        return req, payment, user

    def test_bare_get_callback_does_not_pay(self):
        req, payment, user = self._paid_ready()
        self.client.force_login(user)
        self.client.get(f'/requests/pay/{payment.token}/callback/')
        payment.refresh_from_db()
        req.refresh_from_db()
        self.assertNotEqual(payment.status, RequestPayment.Status.PAID)
        self.assertEqual(req.status, Request.Status.AWAITING_PAYMENT)

    def test_get_callback_cannot_forge_success(self):
        """`?result=success` on a GET must not settle a payment.

        The internal simulator settles on `result`, and it is the production
        default until a real gateway is switched on — so if that parameter were
        honoured on a GET, any signed-in customer could mark their own request
        paid by opening a URL. It is only read from the simulator's own
        CSRF-protected POST form.
        """
        req, payment, user = self._paid_ready()
        self.client.force_login(user)
        self.client.get(f'/requests/pay/{payment.token}/callback/?result=success')
        payment.refresh_from_db()
        req.refresh_from_db()
        self.assertNotEqual(payment.status, RequestPayment.Status.PAID)
        self.assertEqual(req.status, Request.Status.AWAITING_PAYMENT)

    def test_callback_works_without_session(self):
        """Losing the session at the gateway must not strand a real payment."""
        req, payment, _user = self._paid_ready()
        resp = self.client.post(
            f'/requests/pay/{payment.token}/callback/', {'result': 'success'})
        payment.refresh_from_db()
        self.assertEqual(payment.status, RequestPayment.Status.PAID)
        self.assertEqual(resp.status_code, 302)


class ZarinpalBackendTests(TestCase):
    """Gateway wire format, with urllib mocked — no network."""

    def test_get_backend_selects_zarinpal_when_configured(self):
        from apps.core.models import SystemParameter as SP
        self.assertEqual(payments.get_backend().name, 'internal')  # safe default
        for key, value in (
            ('payment_enabled', 'true'), ('payment_provider', 'zarinpal'),
            ('payment_merchant_id', 'M' * 36), ('payment_site_url', 'https://pars-tida.ir'),
        ):
            SP.objects.update_or_create(key=key, defaults={'value': value})
        self.assertEqual(payments.get_backend().name, 'zarinpal')
        # Disabling must fall back to the simulator, never to a live gateway.
        SP.objects.filter(key='payment_enabled').update(value='false')
        self.assertEqual(payments.get_backend().name, 'internal')

    def _mock(self, reply):
        """Patch urlopen on the opener the backend builds; capture the request."""
        from unittest.mock import patch
        captured = {}

        class FakeResp:
            def __init__(self, body):
                self._b = body.encode()

            def read(self):
                return self._b

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class FakeOpener:
            def open(self, req, timeout=None):
                captured['url'] = req.full_url
                captured['body'] = json.loads(req.data.decode())
                return FakeResp(captured['reply'])

        captured['reply'] = reply
        return patch.object(payments.urllib.request, 'build_opener',
                            lambda *a, **k: FakeOpener()), captured

    def test_create_sends_toman_and_returns_startpay(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        payment.status = RequestPayment.Status.PENDING
        patcher, cap = self._mock('{"data":{"code":100,"authority":"A00000000000000000000000000000012345"},"errors":[]}')
        with patcher:
            url = payments.ZarinpalBackend('M' * 36, 'https://pars-tida.ir').create(payment)
        self.assertIn('payment/request.json', cap['url'])
        self.assertEqual(cap['body']['currency'], 'IRT')          # Tomans, not Rials
        self.assertEqual(cap['body']['amount'], 1100)             # not 11000
        self.assertIn('pars-tida.ir', cap['body']['callback_url'])
        self.assertTrue(url.endswith('A00000000000000000000000000000012345'))
        payment.refresh_from_db()
        self.assertEqual(payment.authority, 'A00000000000000000000000000000012345')

    def test_verify_success_and_already_verified(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        payment.authority = 'A' * 36
        payment.save(update_fields=['authority'])
        backend = payments.ZarinpalBackend('M' * 36, 'https://pars-tida.ir')
        for code in (100, 101):
            patcher, _cap = self._mock('{"data":{"code":%d,"ref_id":987654},"errors":[]}' % code)
            data = {'Status': 'OK', 'Authority': 'A' * 36}
            with patcher:
                self.assertTrue(backend.verify(payment, data))
            self.assertEqual(data['ref'], '987654')

    def test_verify_rejects_abort_and_mismatched_authority(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        payment.authority = 'A' * 36
        payment.save(update_fields=['authority'])
        backend = payments.ZarinpalBackend('M' * 36, 'https://pars-tida.ir')
        # Customer aborted — no verify call should even be attempted.
        self.assertFalse(backend.verify(payment, {'Status': 'NOK', 'Authority': 'A' * 36}))
        # An authority belonging to some other transaction must not settle this one.
        self.assertFalse(backend.verify(payment, {'Status': 'OK', 'Authority': 'B' * 36}))

    def test_non_toman_currency_refuses(self):
        req, offer, _ = _approved_contract()
        offer.currency = 'ریال'
        offer.save(update_fields=['currency'])
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        with self.assertRaises(payments.PaymentError):
            payments.ZarinpalBackend('M' * 36, 'https://pars-tida.ir').create(payment)

    def test_gateway_rejection_raises(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        patcher, _cap = self._mock('{"data":[],"errors":{"code":-9,"message":"خطای اعتبارسنجی"}}')
        with patcher, self.assertRaises(payments.PaymentError):
            payments.ZarinpalBackend('M' * 36, 'https://pars-tida.ir').create(payment)


class RialGatewayTests(TestCase):
    """Jibit and DigiPay are Rial-denominated — the ×10 must happen exactly once."""

    def _mock(self, replies):
        """Queue replies in call order (token first, then the operation)."""
        from unittest.mock import patch
        calls = []

        class FakeResp:
            def __init__(self, body):
                self._b = body.encode()

            def read(self):
                return self._b

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class FakeOpener:
            def open(self, req, timeout=None):
                body = req.data.decode() if req.data else ''
                try:
                    parsed = json.loads(body)
                except ValueError:
                    parsed = body
                calls.append({'url': req.full_url, 'body': parsed,
                              'headers': dict(req.header_items())})
                return FakeResp(replies[len(calls) - 1])

        return patch.object(payments.urllib.request, 'build_opener',
                            lambda *a, **k: FakeOpener()), calls

    def test_jibit_create_converts_toman_to_rial(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        patcher, calls = self._mock([
            '{"accessToken":"tok","refreshToken":"r"}',
            '{"purchaseId":"P123","pspSwitchingUrl":"https://napi.jibit.ir/pay/P123"}',
        ])
        with patcher:
            url = payments.JibitBackend('ak', 'sk', 'https://pars-tida.ir').create(payment)
        self.assertEqual(url, 'https://napi.jibit.ir/pay/P123')
        purchase = calls[1]['body']
        self.assertEqual(purchase['amount'], 11000)   # 1100 Toman -> 11000 Rial
        self.assertEqual(purchase['currency'], 'IRR')
        self.assertIn('pars-tida.ir', purchase['callbackUrl'])
        payment.refresh_from_db()
        self.assertEqual(payment.authority, 'P123')

    def test_jibit_verify_accepts_success_and_already_verified(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        payment.authority = 'P123'
        payment.save(update_fields=['authority'])
        backend = payments.JibitBackend('ak', 'sk', 'https://pars-tida.ir')
        for status in ('SUCCESS', 'ALREADY_VERIFIED'):
            patcher, _c = self._mock(
                ['{"accessToken":"tok"}', '{"status":"%s","referenceNumber":"RF9"}' % status])
            data = {'purchaseId': 'P123'}
            with patcher:
                self.assertTrue(backend.verify(payment, data))
            self.assertEqual(data['ref'], 'RF9')
        # A failed verification must not settle the payment.
        patcher, _c = self._mock(['{"accessToken":"tok"}', '{"status":"FAILED"}'])
        with patcher:
            self.assertFalse(backend.verify(payment, {'purchaseId': 'P123'}))

    def test_digipay_create_converts_toman_to_rial(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        patcher, calls = self._mock([
            '{"access_token":"tok","token_type":"bearer"}',
            '{"ticket":"T77","redirectUrl":"https://web.mydigipay.com/pay/T77"}',
        ])
        with patcher:
            url = payments.DigipayBackend(
                'cid', 'csec', 'user', 'pass', 'https://pars-tida.ir').create(payment)
        self.assertEqual(url, 'https://web.mydigipay.com/pay/T77')
        ticket = calls[1]['body']
        self.assertEqual(ticket['amount'], 11000)     # 1100 Toman -> 11000 Rial
        self.assertEqual(ticket['providerId'], str(payment.token))
        self.assertIn('pars-tida.ir', ticket['callbackUrl'])
        payment.refresh_from_db()
        self.assertEqual(payment.authority, 'T77')

    def test_digipay_verify_status_zero_is_success(self):
        req, offer, _ = _approved_contract()
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        backend = payments.DigipayBackend(
            'cid', 'csec', 'user', 'pass', 'https://pars-tida.ir')
        patcher, _c = self._mock(['{"access_token":"tok"}', '{"result":{"status":0}}'])
        data = {'trackingCode': 'TR55'}
        with patcher:
            self.assertTrue(backend.verify(payment, data))
        self.assertEqual(data['ref'], 'TR55')
        # Any non-zero status is a failure.
        patcher, _c = self._mock(['{"access_token":"tok"}', '{"result":{"status":9}}'])
        with patcher:
            self.assertFalse(backend.verify(payment, {'trackingCode': 'TR55'}))
        # No tracking code at all must never settle.
        self.assertFalse(backend.verify(payment, {}))

    def test_rial_gateways_refuse_non_toman_offer(self):
        req, offer, _ = _approved_contract()
        offer.currency = 'دلار'
        offer.save(update_fields=['currency'])
        payment, _ = payments.create_for_offer(request=req, offer=offer)
        with self.assertRaises(payments.PaymentError):
            payments._to_rial(payment)


class IdentityAndVatTests(TestCase):
    def test_mock_identity_default_true(self):
        from apps.requests.services import identity
        matched, _detail = identity.verify_identity(MOBILE, '1234567890')
        self.assertTrue(matched)

    def test_offer_vat_total(self):
        req = lifecycle.create_request(full_name='ت', mobile=MOBILE, province='تهران')
        offer = offers.add_offer(request=req, title='A', amount=1000, vat_percent=10)
        self.assertEqual(offer.vat_amount, 100)
        self.assertEqual(offer.total_amount, 1100)

    def test_payment_blocked_without_identity(self):
        # An approved contract but no identity verification must block payment.
        req = lifecycle.create_request(full_name='ت', mobile=MOBILE, province='تهران')
        offer = offers.add_offer(request=req, title='A', amount=1000)
        contract = offers.select_offer(request=req, offer=offer)
        contracts.request_approval_otp(contract)
        code = OtpVerification.objects.filter(
            mobile=MOBILE, purpose=OtpVerification.Purpose.CONTRACT_APPROVAL, is_used=False,
        ).latest('created_at').code
        contracts.approve_with_otp(contract=contract, code=code)
        with self.assertRaises(payments.PaymentError):
            payments.create_for_offer(request=req, offer=offer)

    def test_payment_amount_includes_vat(self):
        req, offer, _ = _approved_contract()
        payment, _url = payments.create_for_offer(request=req, offer=offer)
        self.assertEqual(payment.amount, offer.total_amount)
        self.assertEqual(payment.amount, 1100)
