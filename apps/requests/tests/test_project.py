"""Second contract, instalments, finance approval and protected files."""
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.requests.models import ContractInstallment, ProjectContract, Request, RequestDocument, RequestPayment
from apps.requests.services import lifecycle, offers, project

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}
PDF = b'%PDF-1.4 test'
PRIVATE = Path(tempfile.mkdtemp(prefix='private-test-'))


def pdf(name='file.pdf'):
    return SimpleUploadedFile(name, PDF, content_type='application/pdf')


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'], PRIVATE_MEDIA_ROOT=PRIVATE)
class ProjectFlowTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(PRIVATE, ignore_errors=True)

    def setUp(self):
        self.customer = User.objects.create_user(username='09120000061', password='p', role='customer')
        self.sales, self.finance, self.tech = (
            User.objects.create_user(username=f'p_{r}', password='p', role=r) for r in ('sales', 'financial', 'technical'))
        self.req = lifecycle.create_request(
            full_name='مشتری', mobile='09120000061', province='تهران', user=self.customer,
            department=Request.Department.SALES, sales_phase=Request.SalesPhase.NEGOTIATION,
            funnel_stage=Request.FunnelStage.SECOND_CONTRACT)

    def form_data(self, **extra):
        today = timezone.localdate()
        data = {'contract_number': 'C-2', 'signed_on': today.isoformat(), 'total_amount': '۳٬۰۰۰'}
        for n in (1, 2, 3):
            data.update({f'title_{n}': f'قسط {n}', f'amount_{n}': '1000',
                         f'due_{n}': (today + timedelta(days=n * 10)).isoformat()})
        return {**data, **extra}

    def contract(self):
        self.client.force_login(self.sales)
        response = self.client.post(reverse('requests:project-contract', args=[self.req.pk]), self.form_data(), **HOST)
        self.assertEqual(response.status_code, 302)
        return ProjectContract.objects.get(request=self.req)

    def receipt(self, item, user=None):
        self.client.force_login(user or self.customer)
        return self.client.post(reverse('requests:installment-receipt', args=[item.pk]), {
            'paid_on': timezone.localdate().isoformat(), 'reference': 'R1', 'receipt': pdf('receipt.pdf')}, **HOST)

    def test_sum_must_match_and_only_sales_records(self):
        self.client.force_login(self.sales)
        page = self.client.post(reverse('requests:project-contract', args=[self.req.pk]),
                                self.form_data(total_amount='9000'), **HOST)
        self.assertEqual(page.status_code, 200)
        self.assertFalse(ProjectContract.objects.exists())
        self.client.force_login(self.finance)
        self.assertEqual(self.client.get(reverse('requests:project-contract', args=[self.req.pk]), **HOST).status_code, 403)

    def test_receipt_needs_finance_approval_and_locks_contract(self):
        contract = self.contract()
        self.assertEqual(contract.installments.count(), 3)
        item = contract.installments.get(number=1)
        self.assertEqual(self.receipt(item).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.status, ContractInstallment.Status.SUBMITTED)
        self.client.force_login(self.sales)
        url = reverse('requests:installment-review', args=[item.pk])
        self.assertEqual(self.client.post(url, {'decision': 'approve'}, **HOST).status_code, 403)
        self.client.force_login(self.finance)
        self.client.post(url, {'decision': 'reject'}, **HOST)
        item.refresh_from_db()
        self.assertEqual(item.status, ContractInstallment.Status.SUBMITTED)
        self.client.post(url, {'decision': 'approve'}, **HOST)
        item.refresh_from_db()
        self.assertEqual((item.status, item.finance_by), (ContractInstallment.Status.APPROVED, self.finance))
        with self.assertRaises(project.ProjectError):
            project.save_contract(self.req, {}, actor=self.sales)

    def test_receipt_rejects_disguised_file(self):
        item = self.contract().installments.first()
        self.client.force_login(self.customer)
        fake = SimpleUploadedFile('r.pdf', b'<script>alert(1)</script>', content_type='application/pdf')
        self.client.post(reverse('requests:installment-receipt', args=[item.pk]),
                         {'paid_on': timezone.localdate().isoformat(), 'receipt': fake}, **HOST)
        item.refresh_from_db()
        self.assertEqual(item.status, ContractInstallment.Status.PENDING)

    def test_files_are_private(self):
        item = self.contract().installments.first()
        self.receipt(item)
        item.refresh_from_db()
        self.assertTrue(Path(item.receipt.path).is_relative_to(PRIVATE))
        url = reverse('requests:installment-receipt-file', args=[item.pk])
        self.assertEqual(self.client.get(url, **HOST).status_code, 200)
        stranger = User.objects.create_user(username='other', password='p', role='customer')
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(url, **HOST).status_code, 403)
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(url, **HOST).status_code, 403)

    def test_document_visibility(self):
        self.client.force_login(self.tech)
        self.client.post(reverse('requests:document-add', args=[self.req.pk]),
                         {'title': 'نقشه', 'kind': 'technical', 'file': pdf(), 'visible_to_customer': '1'}, **HOST)
        document = RequestDocument.objects.get()
        self.assertFalse(document.visible_to_customer)
        self.client.post(reverse('requests:document-add', args=[self.req.pk]),
                         {'title': 'مالی', 'kind': 'payment', 'file': pdf()}, **HOST)
        self.assertEqual(RequestDocument.objects.count(), 1)
        url = reverse('requests:document-file', args=[document.pk])
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(url, **HOST).status_code, 403)
        document.visible_to_customer = True
        document.save()
        self.assertEqual(self.client.get(url, **HOST).status_code, 200)

    def test_customer_sees_schedule_and_finance_queue_counts(self):
        contract = self.contract()
        self.client.force_login(self.customer)
        self.assertContains(self.client.get(reverse('requests:my-detail', args=[self.req.pk]), **HOST), 'C-2')
        self.receipt(contract.installments.first())
        self.client.force_login(self.finance)
        page = self.client.get(reverse('requests:admin-payments'), **HOST)
        self.assertEqual(len(page.context['installments_waiting']), 1)
        self.assertEqual(project.finance_pending_count(), 1)

    def test_online_payment_review_gates_next_stage(self):
        offer = offers.add_offer(request=self.req, title='A', amount=100)
        payment = RequestPayment.objects.create(request=self.req, offer=offer, amount=110,
                                                status=RequestPayment.Status.PAID, paid_at=timezone.now())
        from apps.requests.models import RequestContract
        RequestContract.objects.create(request=self.req, offer=offer, contract_number='F', body='x',
                                       status=RequestContract.Status.APPROVED)
        self.req.funnel_stage = Request.FunnelStage.FIRST_CONTRACT
        self.req.save()
        with self.assertRaises(lifecycle.DepartmentError):
            lifecycle.start_commercial_offer(self.req, actor=self.sales)
        with self.assertRaises(project.ProjectError):
            project.review_payment(payment, decision='approve', note='', actor=self.sales)
        project.review_payment(payment, decision='approve', note='', actor=self.finance)
        lifecycle.start_commercial_offer(self.req, actor=self.sales)
        self.assertEqual(self.req.funnel_stage, Request.FunnelStage.COMMERCIAL_OFFER)
