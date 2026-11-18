"""A customer sees every request made with their mobile, and owns the plant built for it."""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.plants.models import Inverter, Plant
from apps.requests.models import OtpVerification, Request
from apps.requests.services import lifecycle

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}
MOBILE = '09125550001'


def sms_login(client, mobile=MOBILE):
    client.post(reverse('requests:otp-login'), {'mobile': mobile}, **HOST)
    code = OtpVerification.objects.filter(mobile=mobile).latest('id').code
    return client.post(reverse('requests:verify'), {'code': code}, **HOST)


class CustomerSeesTheirRequestsTests(TestCase):
    def test_request_made_after_sign_in_shows_up(self):
        # Signed in once; later an exhibition QR request arrives for the same number.
        sms_login(self.client)
        later = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        resp = self.client.get(reverse('requests:my-list'), **HOST)
        self.assertContains(resp, reverse('requests:my-detail', args=[later.pk]))
        later.refresh_from_db()
        self.assertEqual(later.user.username, MOBILE)

    def test_owner_role_account_gets_its_requests(self):
        u = User(username=MOBILE, phone_number=MOBILE, role='owner')
        u.set_unusable_password()
        u.save()
        req = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        sms_login(self.client)
        req.refresh_from_db()
        self.assertEqual(req.user, u)

    def test_staff_signing_in_by_sms_takes_nobody_elses_request(self):
        staff = User.objects.create_user(username='tech9', password='Zx9!kQ2mVr7t', role='technical')
        staff.phone_number = MOBILE
        staff.save()
        req = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        sms_login(self.client)
        req.refresh_from_db()
        self.assertIsNone(req.user)

    def test_password_account_with_that_number_is_not_trusted(self):
        User.objects.create_user(username=MOBILE, password='Zx9!kQ2mVr7t', role='owner')
        self.assertIsNone(lifecycle.customer_account_for(MOBILE, create=True))


class CommissionPlantTests(TestCase):
    def setUp(self):
        self.tech = User.objects.create_user(username='tech1x', password='Zx9!kQ2mVr7t', role='technical')
        self.client.login(username='tech1x', password='Zx9!kQ2mVr7t')

    def _commission(self, req):
        return self.client.post(reverse('requests:admin-commission-plant', args=[req.pk]), **HOST)

    def test_plant_for_an_unowned_request_belongs_to_the_customer(self):
        req = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        self._commission(req)
        req.refresh_from_db()
        self.assertEqual(req.plant.owner.username, MOBILE)
        self.assertNotEqual(req.plant.owner, self.tech)
        self.assertEqual(req.user, req.plant.owner)
        # ...and the customer sees it on first SMS login.
        self.client.logout()
        sms_login(self.client)
        self.assertContains(self.client.get(reverse('requests:my-plant'), follow=True, **HOST), req.plant.name)

    def test_password_account_blocks_commission(self):
        User.objects.create_user(username=MOBILE, password='Zx9!kQ2mVr7t', role='owner')
        req = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        self._commission(req)
        req.refresh_from_db()
        self.assertIsNone(req.plant)

    def test_inverter_added_from_the_plant_page(self):
        req = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        self._commission(req)
        plant = Request.objects.get(pk=req.pk).plant
        page = self.client.get(reverse('plants:edit', args=[plant.pk]), **HOST)
        add = reverse('plants:inverter-create') + f'?plant={plant.pk}'
        self.assertContains(page, add)
        form = self.client.get(add, **HOST)
        self.assertEqual(str(form.context['form']['plant'].value()), str(plant.pk))
        resp = self.client.post(add, {'plant': plant.pk, 'serial_number': 'INV-9', 'model_name': 'SUN-125',
                                      'status': 'online', 'online': 'on', 'rated_power_kw': '125',
                                      'firmware_version': 'V1', 'manufacturer': 'Huawei'}, **HOST)
        errors = resp.context['form'].errors if resp.status_code == 200 else None
        self.assertRedirects(resp, reverse('plants:edit', args=[plant.pk]), fetch_redirect_response=False, msg_prefix=str(errors))
        self.assertTrue(Inverter.objects.filter(plant=plant, serial_number='INV-9').exists())


class RepairCommandTests(TestCase):
    def test_reports_then_repairs(self):
        tech = User.objects.create_user(username='tech2x', password='Zx9!kQ2mVr7t', role='technical')
        customer = User(username=MOBILE, phone_number=MOBILE, role='customer')
        customer.set_unusable_password()
        customer.save()
        loose = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        other = lifecycle.create_request(full_name='y', mobile='09125550002', province='تهران')
        plant = Plant.objects.create(name='p', owner=tech, external_code='REQ-X', location_name='l',
                                     latitude=0, longitude=0, capacity_kw=0)
        other.plant = plant
        other.save()

        call_command('link_customer_requests')                 # report only
        loose.refresh_from_db(); plant.refresh_from_db()
        self.assertIsNone(loose.user)
        self.assertEqual(plant.owner, tech)

        call_command('link_customer_requests', apply=True)
        loose.refresh_from_db(); plant.refresh_from_db(); other.refresh_from_db()
        self.assertEqual(loose.user, customer)
        self.assertEqual(plant.owner.username, '09125550002')
        self.assertEqual(other.user, plant.owner)


class PlantCardTests(TestCase):
    def test_won_request_shows_the_plant_step_at_the_top(self):
        User.objects.create_user(username='adm9', password='Zx9!kQ2mVr7t', role='admin')
        self.client.login(username='adm9', password='Zx9!kQ2mVr7t')
        req = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        Request.objects.filter(pk=req.pk).update(department='done')
        url = reverse('requests:admin-detail', args=[req.pk])
        html = self.client.get(url, **HOST).content.decode()
        self.assertIn('فروش تکمیل شده؛ نیروگاه هنوز ساخته نشده است.', html)
        self.client.post(reverse('requests:admin-commission-plant', args=[req.pk]), **HOST)
        html = self.client.get(url, **HOST).content.decode()
        self.assertIn('تکمیل نیروگاه و اینورترها', html)
        self.assertNotIn('فروش تکمیل شده؛ نیروگاه هنوز ساخته نشده است.', html)


class LocalTimeTests(TestCase):
    """Date filters and charts are computed without DB time-zone tables."""

    def test_date_filter_uses_local_day(self):
        from datetime import date, datetime
        from django.utils import timezone
        from apps.requests import repositories
        req = lifecycle.create_request(full_name='x', mobile=MOBILE, province='تهران')
        # 01:00 Tehran on 15 Nov is still 14 Nov in UTC.
        at = timezone.make_aware(datetime(2026, 11, 15, 1, 0), timezone.get_current_timezone())
        Request.objects.filter(pk=req.pk).update(created_at=at)
        hits = lambda **kw: list(repositories.filter_requests(**kw).values_list('pk', flat=True))
        self.assertEqual(hits(date_from=date(2026, 11, 15), date_to=date(2026, 11, 15)), [req.pk])
        self.assertEqual(hits(date_to=date(2026, 11, 14)), [])

    def test_owner_chart_and_today_energy(self):
        from datetime import timedelta
        from decimal import Decimal
        from django.utils import timezone
        from apps.plants.models import Equipment, RealtimeMeasurement
        u = User(username=MOBILE, phone_number=MOBILE, role='customer'); u.set_unusable_password(); u.save()
        plant = Plant.objects.create(name='p', owner=u, external_code='X1', location_name='l', latitude=0, longitude=0, capacity_kw=100)
        eq = Equipment.objects.create(plant=plant, category='inverter', name='e', serial_number='E1', health_status='healthy', online=True)
        now = timezone.now()
        for mins, kw in ((10, 50), (20, 70)):
            RealtimeMeasurement.objects.create(timestamp=now - timedelta(minutes=mins), plant=plant, equipment=eq, parameter='power', value=Decimal(kw), unit='kW')
        RealtimeMeasurement.objects.create(timestamp=now - timedelta(minutes=5), plant=plant, equipment=eq, parameter='energy', value=Decimal('12.5'), unit='kWh')
        self.client.force_login(u)
        data = self.client.get(reverse('core:owner-dashboard-data'), **HOST).json()
        self.assertEqual(data['today_energy_kwh'], 12.5)
        self.assertTrue(any(50 <= v <= 70 for v in data['chart']['production']))
