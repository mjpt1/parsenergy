from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.requests.models import Request, RequestPayment
from apps.requests.services import lifecycle, offers

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}


class RequestDeleteTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user(
            username='su', password='p', is_superuser=True, is_staff=True)
        self.admin = User.objects.create_user(username='adm', password='p', role='admin')
        self.sales = User.objects.create_user(username='sal', password='p', role='sales')
        self.req = lifecycle.create_request(full_name='ت', mobile='09120000099', province='تهران')

    def _delete(self, username):
        self.client.login(username=username, password='p')
        return self.client.post(reverse('requests:admin-delete', args=[self.req.id]), **HOST)

    def test_superadmin_can_delete(self):
        resp = self._delete('su')
        self.assertRedirects(resp, reverse('requests:admin-list'), fetch_redirect_response=False)
        self.assertFalse(Request.objects.filter(pk=self.req.id).exists())

    def test_admin_can_delete_with_offers(self):
        lifecycle.refer_marketing_to_sales(self.req, actor=self.admin)
        lifecycle.refer_sales_to_technical(self.req, actor=self.admin)
        offers.add_offer(request=self.req, title='A', amount=1000, created_by=self.admin)
        self._delete('adm')
        self.assertFalse(Request.objects.filter(pk=self.req.id).exists())

    def test_admin_can_delete_with_contract_and_pending_payment(self):
        from apps.requests.models import RequestContract
        lifecycle.refer_marketing_to_sales(self.req, actor=self.admin)
        lifecycle.refer_sales_to_technical(self.req, actor=self.admin)
        offer = offers.add_offer(request=self.req, title='A', amount=1000, created_by=self.admin)
        RequestContract.objects.create(request=self.req, offer=offer, contract_number='C-T-1')
        RequestPayment.objects.create(request=self.req, offer=offer, amount=1000)
        resp = self._delete('adm')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Request.objects.filter(pk=self.req.id).exists())
        self.assertFalse(RequestContract.objects.filter(contract_number='C-T-1').exists())

    def test_sales_cannot_delete(self):
        resp = self._delete('sal')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Request.objects.filter(pk=self.req.id).exists())

    def test_paid_request_is_kept(self):
        lifecycle.refer_marketing_to_sales(self.req, actor=self.admin)
        lifecycle.refer_sales_to_technical(self.req, actor=self.admin)
        offer = offers.add_offer(request=self.req, title='A', amount=1000, created_by=self.admin)
        RequestPayment.objects.create(request=self.req, offer=offer, amount=1000,
                                      status=RequestPayment.Status.PAID)
        self._delete('su')
        self.assertTrue(Request.objects.filter(pk=self.req.id).exists())

    def test_button_shown_only_to_management(self):
        url = reverse('requests:admin-detail', args=[self.req.id])
        delete_url = reverse('requests:admin-delete', args=[self.req.id])
        self.client.login(username='adm', password='p')
        self.assertContains(self.client.get(url, **HOST), delete_url)
        self.client.login(username='sal', password='p')
        self.assertNotContains(self.client.get(url, **HOST), delete_url)
