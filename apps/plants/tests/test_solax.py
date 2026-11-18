from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.plants import solax
from apps.plants.forms import CloudAccountForm, InverterForm
from apps.plants.models import CloudAccount, Inverter, Plant, RealtimeMeasurement, TelemetryReading

HOST = {'HTTP_HOST': 'localhost'}
SN = 'H34A20I1234567'


def fake_cloud(daily_values):
    """Stand-in for SolaX: a token, then one realtime row per call with the given daily yields."""
    calls = {'token': 0, 'data': 0}
    days = iter(daily_values)

    def call(url, *, data=None, token=None):
        if url.endswith('/oauth/token'):
            calls['token'] += 1
            return {'code': 0, 'result': {'access_token': f't{calls["token"]}', 'expires_in': 2591999}}
        calls['data'] += 1
        assert 'snList=' + SN in url and token
        return {'code': 10000, 'result': [{'deviceSn': SN, 'totalActivePower': 48250, 'acVoltage1': 230, 'acCurrent1': 70, 'acVoltage2': 230, 'acCurrent2': 70, 'acVoltage3': 230, 'acCurrent3': 70,
                                           'dailyYield': next(days), 'deviceStatus': 102, 'gridFrequency': 50.01}]}
    return call, calls


class SolaxSyncTests(TestCase):
    def setUp(self):
        owner = get_user_model().objects.create_user(username='09390000000', password='x', role='customer')
        self.plant = Plant.objects.create(name='p', owner=owner, external_code='P1', location_name='l',
                                          latitude=0, longitude=0, capacity_kw=200)
        self.account = CloudAccount.objects.create(name='yazd', client_id='cid', client_secret='sec')
        self.inv = Inverter.objects.create(plant=self.plant, serial_number=SN, model_name='X3', rated_power_kw=100,
                                           data_source='solax', cloud_account=self.account)

    def test_sync_stores_power_and_energy_since_last_read(self):
        call, calls = fake_cloud([Decimal('120.5'), Decimal('121.0'), Decimal('3.0')])
        with mock.patch.object(solax, '_call', side_effect=call):
            for _ in range(3):
                call_command('sync_solax', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.assertEqual(calls['token'], 1)          # token reused, not renewed each sync
        energies = list(TelemetryReading.objects.order_by('id').values_list('energy_kwh', flat=True))
        self.assertEqual(energies, [Decimal('120.5'), Decimal('0.5'), Decimal('3.0')])   # midnight reset
        self.inv.refresh_from_db()
        self.assertTrue(self.inv.online)
        self.assertEqual(self.inv.last_sync_error, '')
        self.assertEqual(RealtimeMeasurement.objects.filter(parameter='power').last().value, Decimal('48.25'))

    def test_unknown_serial_is_reported_on_the_inverter(self):
        def call(url, *, data=None, token=None):
            if url.endswith('/oauth/token'):
                return {'code': 0, 'result': {'access_token': 't', 'expires_in': 100000}}
            return {'code': 10000, 'result': []}
        with mock.patch.object(solax, '_call', side_effect=call):
            stored, problems = solax.sync_account(self.account)
        self.inv.refresh_from_db()
        self.assertEqual(stored, 0)
        self.assertIn('پیدا نشد', self.inv.last_sync_error)

    def test_bad_credentials_are_reported(self):
        with mock.patch.object(solax, '_call', return_value={'code': 1, 'message': 'invalid_client'}):
            solax.sync_account(self.account)
        self.account.refresh_from_db()
        self.assertIn('invalid_client', self.account.last_error)


class FormTests(TestCase):
    def test_solax_inverter_needs_an_account_and_serial_is_normalised(self):
        owner = get_user_model().objects.create_user(username='u1', password='x', role='customer')
        plant = Plant.objects.create(name='p', owner=owner, external_code='P2', location_name='l', latitude=0, longitude=0, capacity_kw=1)
        base = {'plant': plant.pk, 'serial_number': ' h34a20i1234567 ', 'model_name': 'X3', 'manufacturer': 'SolaX',
                'rated_power_kw': '100', 'status': 'online', 'data_source': 'solax'}
        f = InverterForm(base)
        self.assertFalse(f.is_valid())
        self.assertIn('cloud_account', f.errors)
        acc = CloudAccount.objects.create(name='a', client_id='c', client_secret='s')
        f = InverterForm({**base, 'cloud_account': acc.pk})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data['serial_number'], SN)

    def test_blank_secret_on_edit_keeps_the_old_one(self):
        acc = CloudAccount.objects.create(name='a', client_id='c', client_secret='old', access_token='tok')
        f = CloudAccountForm({'name': 'a2', 'provider': 'solax', 'business_type': 4, 'api_host': acc.api_host, 'client_id': 'c', 'client_secret': ''}, instance=acc)
        self.assertTrue(f.is_valid(), f.errors)
        f.save()
        acc.refresh_from_db()
        self.assertEqual((acc.client_secret, acc.access_token), ('old', 'tok'))


class AccessTests(TestCase):
    def test_only_admin_and_technical_reach_cloud_accounts(self):
        U = get_user_model()
        for role, code in (('customer', 403), ('sales', 403), ('technical', 200), ('admin', 200)):
            U.objects.create_user(username=f'r_{role}', password='Zx9!kQ2mVr7t', role=role)
            self.client.login(username=f'r_{role}', password='Zx9!kQ2mVr7t')
            self.assertEqual(self.client.get(reverse('plants:cloud-accounts'), **HOST).status_code, code, role)
            self.client.logout()
        html = self.client.get(reverse('plants:cloud-accounts'), **HOST)
        self.assertNotEqual(html.status_code, 200)


class PageTests(TestCase):
    def test_inverter_form_and_sync_button_render(self):
        U = get_user_model()
        U.objects.create_user(username='tech_p', password='Zx9!kQ2mVr7t', role='technical')
        owner = U.objects.create_user(username='09390000001', password='x', role='customer')
        plant = Plant.objects.create(name='p', owner=owner, external_code='P3', location_name='l', latitude=0, longitude=0, capacity_kw=1)
        acc = CloudAccount.objects.create(name='a', client_id='cid', client_secret='s3cr3t-value')
        inv = Inverter.objects.create(plant=plant, serial_number=SN, model_name='X3', data_source='solax', cloud_account=acc)
        self.client.login(username='tech_p', password='Zx9!kQ2mVr7t')
        self.assertContains(self.client.get(reverse('plants:inverter-create'), **HOST), 'اتصال به داده‌های زنده')
        html = self.client.get(reverse('plants:inverter-edit', args=[inv.pk]), **HOST)
        self.assertContains(html, reverse('plants:inverter-sync', args=[inv.pk]))
        edit = self.client.get(reverse('plants:cloud-account-edit', args=[acc.pk]), **HOST)
        self.assertNotContains(edit, 's3cr3t-value')   # the secret is never sent back to the browser


class PowerUnitTests(TestCase):
    def test_kilowatts_and_watts_are_told_apart(self):
        kw_row = {'totalactivepower': 66, 'acvoltage1': 239.7, 'accurrent1': 93.1, 'acvoltage2': 240.3,
                  'accurrent2': 93.0, 'acvoltage3': 240, 'accurrent3': 92}       # the Yazd X3-FORTH
        self.assertEqual(solax.total_kw(kw_row, 125), Decimal('66'))
        w_row = {'totalactivepower': 6000, 'acvoltage1': 230, 'accurrent1': 8.7, 'acvoltage2': 230,
                 'accurrent2': 8.7, 'acvoltage3': 230, 'accurrent3': 8.7}
        self.assertEqual(solax.total_kw(w_row, 10), Decimal('6'))
        self.assertEqual(solax.total_kw({'totalactivepower': 6000}, 10), Decimal('6'))
        self.assertEqual(solax.total_kw({'totalactivepower': 80}, 125), Decimal('80'))
