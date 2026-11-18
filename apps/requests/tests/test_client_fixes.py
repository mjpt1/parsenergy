"""Issues reported by the client after the first phase."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.requests.forms import ProfileCompletionForm
from apps.requests.models import Request, RequestContract
from apps.requests.services import contracts, lifecycle, offers, payments
from apps.requests.todo import build_todo

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}


def make_request(**values):
    req = lifecycle.create_request(full_name='مشتری', mobile='09120000001', province='تهران')
    for key, value in values.items():
        setattr(req, key, value)
    req.save()
    return req


def staff(role):
    return User.objects.create_user(username=role, password='p', role=role)


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class ProfileTests(TestCase):
    def test_customer_profile_uses_customer_shell(self):
        user = User.objects.create_user(username='09120000002', password='p', role='owner')
        self.client.force_login(user)
        response = self.client.get(reverse('accounts:profile'), **HOST)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'base_portal.html')
        self.assertIsNotNone(response.context['profile_form'])

    def test_staff_profile_keeps_staff_shell_without_customer_form(self):
        self.client.force_login(staff('sales'))
        response = self.client.get(reverse('accounts:profile'), **HOST)
        self.assertTemplateUsed(response, 'base.html')
        self.assertIsNone(response.context['profile_form'])

    def test_profile_accepts_company_national_id(self):
        data = {'full_name': 'شرکت', 'mobile': '09120000002', 'national_id': '۱۰۱۰۱۲۳۴۵۶۷'}
        form = ProfileCompletionForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['national_id'], '10101234567')
        self.assertFalse(ProfileCompletionForm({**data, 'national_id': '123'}).is_valid())


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class OfferPriceTests(TestCase):
    def setUp(self):
        self.req = make_request(department=Request.Department.SALES,
                                sales_phase=Request.SalesPhase.NEGOTIATION,
                                status=Request.Status.OFFERED, identity_verified=True)
        self.offer = offers.add_offer(request=self.req, title='فنی', amount=0)

    def test_unpriced_offer_cannot_become_contract_or_payment(self):
        with self.assertRaises(offers.OfferError):
            offers.select_offer(request=self.req, offer=self.offer)
        with self.assertRaises(contracts.ContractError):
            contracts.generate_contract(request=self.req, offer=self.offer)
        with self.assertRaises(payments.PaymentError):
            RequestContract.objects.create(request=self.req, offer=self.offer, contract_number='T-1',
                                           body='x', status=RequestContract.Status.APPROVED)
            payments.create_for_offer(request=self.req, offer=self.offer)

    def test_technical_price_is_ignored_and_sales_sets_it(self):
        technical_req = make_request(department=Request.Department.TECHNICAL)
        self.client.force_login(staff('technical'))
        self.client.post(reverse('requests:admin-offer-add', args=[technical_req.pk]),
                         {'title': 'طرح', 'amount': '5000'}, **HOST)
        self.assertEqual(technical_req.offers.get().amount, Decimal('0'))
        self.client.force_login(staff('sales'))
        self.client.post(reverse('requests:admin-offer-price', args=[self.offer.pk]),
                         {'amount': '۷۰٬۰۰۰٬۰۰۰'}, **HOST)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.amount, Decimal('70000000'))

    def test_approved_contract_keeps_its_price(self):
        self.offer.amount = Decimal('10')
        self.offer.save()
        RequestContract.objects.create(request=self.req, offer=self.offer, contract_number='T-2',
                                       body='x', status=RequestContract.Status.APPROVED)
        with self.assertRaises(offers.OfferError):
            offers.set_price(offer=self.offer, amount=20)


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class QueueTests(TestCase):
    def test_queue_matches_badge_and_closed_stays_reachable(self):
        open_req = make_request()
        closed = make_request(status=Request.Status.CLOSED)
        self.client.force_login(staff('sales'))
        response = self.client.get(reverse('requests:admin-list'), **HOST)
        ids = [r.pk for r in response.context['requests']]
        self.assertEqual(ids, [open_req.pk])
        response = self.client.get(reverse('requests:admin-list'), {'status': 'closed'}, **HOST)
        self.assertEqual([r.pk for r in response.context['requests']], [closed.pk])

    def test_overdue_card_opens_only_overdue_requests(self):
        late = make_request(stage_entered_at=timezone.now() - timedelta(days=30))
        make_request(stage_entered_at=timezone.now())
        admin = staff('admin')
        url = next(i['url'] for i in build_todo('admin', {'overdue': 1}, {}, admin) if i['tone'] == 'bad')
        self.client.force_login(admin)
        response = self.client.get(url, **HOST)
        self.assertEqual([r.pk for r in response.context['requests']], [late.pk])

    def test_operations_reaches_plant_sections(self):
        self.client.force_login(staff('operations'))
        for name in ('plants:sections', 'plants:inverters', 'plants:inverter-create', 'plants:create',
                     'plants:equipment', 'plants:sensors', 'plants:transformers', 'plants:gateways',
                     'plants:cloud-accounts', 'alerts:list', 'alerts:events'):
            self.assertEqual(self.client.get(reverse(name), **HOST).status_code, 200, name)

    def test_customer_is_not_told_an_unpriced_offer_is_ready(self):
        from apps.requests.progress import customer_progress
        req = make_request(department=Request.Department.SALES, sales_phase=Request.SalesPhase.NEGOTIATION)
        offer = offers.add_offer(request=req, title='فنی', amount=0)
        req.refresh_from_db()
        self.assertFalse(customer_progress(req)['your_turn'])
        offer.amount = Decimal('100')
        offer.save()
        self.assertTrue(customer_progress(req)['your_turn'])

    def test_plant_hardware_pages_are_for_plant_staff_only(self):
        names = [f'plants:{page}' for page in ('sensors', 'meters', 'equipment', 'transformers', 'gateways',
                                               'sensor-create', 'meter-create', 'equipment-create',
                                               'transformer-create', 'gateway-create')]
        for role in ('customer', 'owner', 'financial', 'sales', 'marketing'):
            self.client.force_login(User.objects.create_user(username=f'blocked-{role}', password='p', role=role))
            for name in names:
                self.assertEqual(self.client.get(reverse(name), **HOST).status_code, 403, (role, name))
        for role in ('admin', 'technical', 'operations'):
            self.client.force_login(User.objects.create_user(username=f'allowed-{role}', password='p', role=role))
            for name in names:
                self.assertEqual(self.client.get(reverse(name), **HOST).status_code, 200, (role, name))
