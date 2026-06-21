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
