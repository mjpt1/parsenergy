from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.requests.models import Request


class AdminListPaginationTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='boss', password='Zx9!kQ2mVr7t', role='admin')
        for i in range(30):
            Request.objects.create(full_name=f'n{i}', mobile=f'0912000{i:04d}', province='تهران')
        self.client.login(username='boss', password='Zx9!kQ2mVr7t')

    def test_list_shows_next_page_link_and_keeps_filters(self):
        resp = self.client.get(reverse('requests:admin-list') + '?province=تهران', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'page=2')
        self.assertContains(resp, 'province=')

    def test_second_page_has_the_rest(self):
        resp = self.client.get(reverse('requests:admin-list') + '?page=2', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context['requests']), 5)


class MultiFilterTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='boss2', password='Zx9!kQ2mVr7t', role='admin')
        for prov in ('تهران', 'فارس', 'گیلان'):
            Request.objects.create(full_name=prov, mobile='09120000001', province=prov)
        self.client.login(username='boss2', password='Zx9!kQ2mVr7t')

    def test_two_ticked_provinces_show_both(self):
        url = reverse('requests:admin-list') + '?province=تهران&province=فارس'
        resp = self.client.get(url, HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({r.province for r in resp.context['requests']}, {'تهران', 'فارس'})
        self.assertContains(resp, 'type="checkbox" name="province"')

    def test_one_ticked_still_works(self):
        resp = self.client.get(reverse('requests:admin-list') + '?province=گیلان', HTTP_HOST='localhost')
        self.assertEqual([r.province for r in resp.context['requests']], ['گیلان'])


class MoreMultiFilterTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_superuser(username='b3', password='Zx9!kQ2mVr7t', role='admin')
        for name, city in (('علی', 'شیراز'), ('رضا', 'رشت'), ('مینا', 'کرج')):
            Request.objects.create(full_name=name, mobile='09120000002', province='x', city=city)
        self.client.login(username='b3', password='Zx9!kQ2mVr7t')

    def _names(self, qs):
        resp = self.client.get(reverse('requests:admin-list') + qs, HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        return {r.full_name for r in resp.context['requests']}

    def test_several_cities(self):
        self.assertEqual(self._names('?city=شیراز&city=رشت'), {'علی', 'رضا'})

    def test_search_with_comma(self):
        self.assertEqual(self._names('?q=علی، مینا'), {'علی', 'مینا'})

    def test_both_crm_boxes_mean_all(self):
        self.assertEqual(len(self._names('?crm_transferred=1&crm_transferred=0')), 3)


class CompanyColumnTests(TestCase):
    def test_company_shows_and_is_searchable(self):
        from apps.leads.models import Lead, LeadSource
        get_user_model().objects.create_superuser(username='b4', password='Zx9!kQ2mVr7t', role='admin')
        mk = get_user_model().objects.create_user(username='mk9', password='x', role='marketing')
        src = LeadSource.objects.create(name='s', marketer=mk, event_name='E')
        req = Request.objects.create(full_name='حسن', mobile='09120000003', province='x')
        Lead.objects.create(request=req, source=src, marketer=mk, company='شرکت آفتاب')
        Request.objects.create(full_name='دیگری', mobile='09120000004', province='x')
        self.client.login(username='b4', password='Zx9!kQ2mVr7t')
        resp = self.client.get(reverse('requests:admin-list') + '?q=آفتاب', HTTP_HOST='localhost')
        self.assertContains(resp, 'شرکت آفتاب')
        self.assertEqual([r.full_name for r in resp.context['requests']], ['حسن'])


class ReportTests(TestCase):
    def setUp(self):
        from apps.leads.models import Lead, LeadSource
        get_user_model().objects.create_superuser(username='b5', password='Zx9!kQ2mVr7t', role='admin')
        mk = get_user_model().objects.create_user(username='mk8', password='x', role='marketing')
        src = LeadSource.objects.create(name='s', marketer=mk, event_name='E')
        for i in range(30):
            Request.objects.create(full_name=f'n{i}', mobile='09120000005', province='x')
        req = Request.objects.create(full_name='با شرکت', mobile='09120000006', province='x')
        Lead.objects.create(request=req, source=src, marketer=mk, company='شرکت ماه')
        self.client.login(username='b5', password='Zx9!kQ2mVr7t')

    def test_print_has_every_request_and_company(self):
        resp = self.client.get(reverse('requests:admin-list') + '?print=1', HTTP_HOST='localhost')
        self.assertEqual(len(resp.context['requests']), 31)
        self.assertContains(resp, 'شرکت ماه')

    def test_excel_has_company_column(self):
        from apps.leads import exports
        self.assertIn('شرکت', exports.REQUEST_HEADERS)
        rows = exports.request_rows(Request.objects.all())
        self.assertIn('شرکت ماه', [r[2] for r in rows])
        resp = self.client.get(reverse('requests:admin-list') + '?export=excel', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
