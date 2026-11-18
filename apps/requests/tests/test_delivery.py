"""Contractor accounts, project insurance and the equipment list."""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.requests.models import ContractorAssignment, ProjectEquipment, ProjectInsurance, Request, RequestDocument
from apps.requests.services import delivery, lifecycle
from apps.requests.todo import build_todo

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}
PRIVATE = Path(tempfile.mkdtemp(prefix='delivery-test-'))


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'], PRIVATE_MEDIA_ROOT=PRIVATE)
class DeliveryTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVATE, ignore_errors=True)

    def setUp(self):
        self.customer = User.objects.create_user(username='09120000071', password='p', role='customer')
        self.boss, self.tech, self.ops, self.sales, self.finance = (
            User.objects.create_user(username=f'd_{r}', password='p', role=r)
            for r in ('admin', 'technical', 'operations', 'sales', 'financial'))
        self.contractor = User.objects.create_user(username='builder', password='p', role='contractor',
                                                   first_name='سازنده', phone_number='09120000072')
        self.req = lifecycle.create_request(full_name='مشتری محرمانه', mobile='09120000071', province='یزد',
                                            user=self.customer, department='done', funnel_stage='execution',
                                            install_address='آدرس نصب')

    def assign(self, user=None, **extra):
        self.client.force_login(user or self.ops)
        return self.client.post(reverse('requests:contractor-assign', args=[self.req.pk]), {
            'contractor': self.contractor.pk, 'scope': 'نصب سازه', **extra}, **HOST)

    def test_contractor_sees_only_connected_project_and_no_customer_by_default(self):
        self.assertEqual(self.assign().status_code, 302)
        self.client.force_login(self.contractor)
        self.assertRedirects(self.client.get(reverse('dashboard'), **HOST), reverse('requests:contractor-home'),
                             fetch_redirect_response=False)
        page = self.client.get(reverse('requests:contractor-project', args=[self.req.pk]), **HOST)
        self.assertContains(page, 'آدرس نصب')
        self.assertNotContains(page, 'مشتری محرمانه')
        other = lifecycle.create_request(full_name='دیگر', mobile='09120000073', province='تهران')
        self.assertEqual(self.client.get(reverse('requests:contractor-project', args=[other.pk]), **HOST).status_code, 403)

    def test_contractor_is_kept_out_of_every_other_area(self):
        self.client.force_login(self.contractor)
        for url in (reverse('requests:admin-list'), reverse('plants:list'), reverse('requests:admin-detail', args=[self.req.pk]),
                    reverse('requests:my-list'), reverse('requests:equipment-document', args=[self.req.pk])):
            self.assertRedirects(self.client.get(url, **HOST), reverse('requests:contractor-home'),
                                 fetch_redirect_response=False)
        self.assertEqual(self.client.post(reverse('requests:admin-list'), **HOST).status_code, 403)
        self.assertEqual(self.client.get(reverse('accounts:profile'), **HOST).status_code, 200)

    def test_contact_sharing_needs_operations_or_management(self):
        self.assign(self.tech, share_contact='on')
        self.assertFalse(ContractorAssignment.objects.get().share_contact)
        ContractorAssignment.objects.all().delete()
        self.assign(self.ops, share_contact='on')
        self.client.force_login(self.contractor)
        self.assertContains(self.client.get(reverse('requests:contractor-project', args=[self.req.pk]), **HOST), 'مشتری محرمانه')

    def test_history_rating_and_access_ends_with_the_job(self):
        self.assign()
        job = ContractorAssignment.objects.get()
        self.client.post(reverse('requests:contractor-finish', args=[job.pk]), {'status': 'done'}, **HOST)
        job.refresh_from_db()
        self.assertEqual(job.status, 'active')
        self.client.post(reverse('requests:contractor-finish', args=[job.pk]), {'status': 'done', 'rating': '4'}, **HOST)
        job.refresh_from_db()
        self.assertEqual((job.status, job.rating), ('done', 4))
        self.assertContains(self.client.get(reverse('requests:contractor-detail', args=[self.contractor.pk]), **HOST), 'نصب سازه')
        self.client.force_login(self.contractor)
        self.assertEqual(self.client.get(reverse('requests:contractor-project', args=[self.req.pk]), **HOST).status_code, 403)

    def test_contractor_report_and_shared_document(self):
        self.assign()
        doc = RequestDocument.objects.create(request=self.req, stage='execution', title='نقشه', original_name='n.pdf',
                                             file=SimpleUploadedFile('n.pdf', b'%PDF-x'), visible_to_contractor=True)
        hidden = RequestDocument.objects.create(request=self.req, stage='execution', title='سری', original_name='s.pdf',
                                                file=SimpleUploadedFile('s.pdf', b'%PDF-x'))
        self.client.force_login(self.contractor)
        self.assertEqual(self.client.get(reverse('requests:document-file', args=[doc.pk]), **HOST).status_code, 200)
        self.assertEqual(self.client.get(reverse('requests:document-file', args=[hidden.pk]), **HOST).status_code, 403)
        self.client.post(reverse('requests:contractor-report', args=[self.req.pk]), {'body': 'سازه نصب شد'}, **HOST)
        self.assertTrue(self.req.stage_notes.filter(created_by=self.contractor, body__contains='سازه نصب شد').exists())

    def policy_data(self, **extra):
        today = timezone.localdate()
        return {'phase': 'execution', 'kind': 'liability', 'insurer': 'بیمه', 'policy_number': 'P-1',
                'start_date': today.isoformat(), 'end_date': (today + timedelta(days=10)).isoformat(),
                'visible_to_customer': 'on', **extra}

    def test_insurance_rules_warning_and_visibility(self):
        self.assertEqual(delivery.insurance_gap(self.req), 'دورهٔ اجرا')
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse('requests:insurance-add', args=[self.req.pk]), **HOST).status_code, 403)
        self.client.force_login(self.finance)
        upload = SimpleUploadedFile('p.pdf', b'%PDF-x', content_type='application/pdf')
        response = self.client.post(reverse('requests:insurance-add', args=[self.req.pk]),
                                    self.policy_data(file=upload, coverage_amount='۱٬۰۰۰'), **HOST)
        self.assertEqual(response.status_code, 302)
        policy = ProjectInsurance.objects.get()
        self.assertEqual(policy.coverage_amount, 1000)
        self.assertEqual(delivery.insurance_gap(self.req), '')
        self.assertTrue(policy.expires_soon)
        self.assertTrue(any('بیمه‌نامه' in i['text'] for i in build_todo('admin', {}, {}, self.boss)))
        self.client.force_login(self.customer)
        self.assertContains(self.client.get(reverse('requests:my-detail', args=[self.req.pk]), **HOST), 'بیمهٔ مسئولیت')
        self.assertEqual(self.client.get(reverse('requests:insurance-file', args=[policy.pk]), **HOST).status_code, 200)
        policy.visible_to_customer = False
        policy.save()
        self.assertEqual(self.client.get(reverse('requests:insurance-file', args=[policy.pk]), **HOST).status_code, 403)

    def test_equipment_list_for_staff_customer_print_and_excel(self):
        self.client.force_login(self.tech)
        add = reverse('requests:equipment-add', args=[self.req.pk])
        self.client.post(add, {'category': 'panel', 'name': 'پنل ۶۲۰', 'quantity': '187', 'unit': 'عدد',
                               'visible_to_customer': 'on'}, **HOST)
        self.client.post(add, {'category': 'other', 'name': 'قلم داخلی', 'quantity': '1', 'unit': 'عدد'}, **HOST)
        self.assertEqual(ProjectEquipment.objects.count(), 2)
        self.client.force_login(self.sales)
        self.assertEqual(self.client.get(add, **HOST).status_code, 403)
        self.client.force_login(self.customer)
        page = self.client.get(reverse('requests:equipment-document', args=[self.req.pk]), **HOST)
        self.assertContains(page, 'پنل ۶۲۰')
        self.assertNotContains(page, 'قلم داخلی')
        excel = self.client.get(reverse('requests:equipment-document', args=[self.req.pk]), {'format': 'excel'}, **HOST)
        self.assertEqual(excel.status_code, 200)
        self.assertTrue(excel.content.startswith(b'PK'))
        stranger = User.objects.create_user(username='nobody', password='p', role='customer')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse('requests:equipment-document', args=[self.req.pk]), **HOST).status_code, 403)

    def test_case_page_shows_all_three_sections(self):
        self.client.force_login(self.boss)
        page = self.client.get(reverse('requests:admin-detail', args=[self.req.pk]), **HOST)
        for text in ('فهرست تجهیزات پروژه', 'بیمه‌نامه‌ها', 'پیمانکاران پروژه'):
            self.assertContains(page, text)
        self.assertEqual(Request.objects.filter(pk=self.req.pk).count(), 1)

    def test_contractor_with_history_is_kept(self):
        self.assign()
        self.client.force_login(self.boss)
        self.client.post(reverse('accounts:staff-manage-delete', args=[self.contractor.pk]), **HOST)
        self.assertTrue(User.objects.filter(pk=self.contractor.pk).exists())
