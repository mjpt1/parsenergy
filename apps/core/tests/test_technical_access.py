"""What the technical team can reach, and which stored secrets stay out of view."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import APIConnection, SettingChangeRequest, SystemParameter
from apps.plants.models import Inverter, Plant, TelemetryReading

User = get_user_model()
SECRET = 'very-secret-value-123'


class TechnicalSettingsTests(TestCase):
    def setUp(self):
        self.tech = User.objects.create_user('tech', password='x', role='technical')
        self.client.force_login(self.tech)

    def test_opens_the_four_settings_areas(self):
        for name in ('core:connections', 'core:connections-create', 'core:protocols', 'core:protocols-create',
                     'core:parameters', 'core:parameters-create', 'core:integration-settings', 'core:inverter-api'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_other_admin_settings_stay_closed(self):
        for name in ('core:security', 'core:backups', 'core:logs', 'core:ai-settings'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_sales_stays_out(self):
        self.client.force_login(User.objects.create_user('s', password='x', role='sales'))
        self.assertEqual(self.client.get(reverse('core:parameters')).status_code, 403)

    def test_menu_lists_monitoring_and_settings(self):
        page = self.client.get(reverse('plants:list')).content.decode()
        for name in ('plants:dashboard', 'alerts:events', 'alerts:list', 'reports:center', 'analytics:dashboard',
                     'plants:transformers', 'plants:gateways', 'core:integration-settings',
                     'core:connections', 'core:protocols', 'core:parameters'):
            self.assertIn(f'href="{reverse(name)}"', page, name)

    def test_integration_keys_are_write_only(self):
        SystemParameter.objects.create(key='sms_api_key', value=SECRET, is_secret=True)
        SystemParameter.objects.create(key='payment_api_key', value='old-payment', is_secret=True)
        url = reverse('core:integration-settings')
        page = self.client.get(url)
        self.assertNotContains(page, SECRET)
        data = {k: v for k, v in page.context['form'].initial.items() if v not in (False, None)}
        data.update({'sms_api_key': '', 'payment_api_key': 'new-payment', 'sms_sender': '3000'})
        self.assertEqual(self.client.post(url, data).status_code, 302)
        # Nothing goes live yet, and an empty key box asks for no change.
        self.assertEqual(SystemParameter.objects.get(key='sms_api_key').value, SECRET)
        self.assertEqual(SystemParameter.objects.get(key='payment_api_key').value, 'old-payment')
        self.assertFalse(SystemParameter.objects.filter(key='sms_sender').exists())
        change = SettingChangeRequest.objects.get()
        self.assertEqual(set(change.changes), {'payment_api_key', 'sms_sender'})

    def test_admin_still_sees_stored_keys(self):
        SystemParameter.objects.create(key='sms_api_key', value=SECRET, is_secret=True)
        self.client.force_login(User.objects.create_user('boss', password='x', role='admin'))
        self.assertContains(self.client.get(reverse('core:integration-settings')), SECRET)

    def test_secret_parameter_cannot_be_read_renamed_or_deleted(self):
        param = SystemParameter.objects.create(key='ai_api_key', value=SECRET)
        url = reverse('core:parameters-edit', args=[param.pk])
        self.assertNotContains(self.client.get(url), SECRET)
        self.client.post(url, {'key': 'renamed', 'value': '', 'description': 'd'})
        param.refresh_from_db()
        self.assertEqual((param.key, param.value, param.description), ('ai_api_key', SECRET, 'd'))
        self.assertEqual(self.client.post(reverse('core:parameters-delete', args=[param.pk])).status_code, 403)
        self.assertTrue(SystemParameter.objects.filter(pk=param.pk).exists())

    def test_plain_parameter_is_editable(self):
        param = SystemParameter.objects.create(key='tariff.energy_rial_per_kwh', value='100')
        url = reverse('core:parameters-edit', args=[param.pk])
        self.assertContains(self.client.get(url), '100')
        self.client.post(url, {'key': param.key, 'value': '200'})
        param.refresh_from_db()
        self.assertEqual(param.value, '200')

    def test_connection_token_is_write_only(self):
        conn = APIConnection.objects.create(name='c', base_url='https://example.com', token=SECRET)
        url = reverse('core:connections-edit', args=[conn.pk])
        self.assertNotContains(self.client.get(url), SECRET)
        self.client.post(url, {'name': 'c2', 'base_url': 'https://example.com', 'auth_type': 'token',
                               'token': '', 'is_active': 'on'})
        conn.refresh_from_db()
        self.assertEqual((conn.name, conn.token), ('c2', SECRET))


class ServiceChangeApprovalTests(TestCase):
    def setUp(self):
        self.tech = User.objects.create_user('tech', password='x', role='technical')
        self.admin = User.objects.create_user('boss', password='x', role='admin')
        SystemParameter.objects.create(key='payment_api_key', value='old-payment', is_secret=True)
        SystemParameter.objects.create(key='payment_provider', value='internal')
        self.url = reverse('core:integration-settings')
        self.client.force_login(self.tech)

    def _submit(self, **values):
        data = {k: v for k, v in self.client.get(self.url).context['form'].initial.items()
                if v not in (False, None)}
        data.update({'payment_api_key': '', **values})
        return self.client.post(self.url, data)

    def _value(self, key):
        return SystemParameter.objects.get(key=key).value

    def test_map_key_applies_at_once_but_payment_waits(self):
        self._submit(neshan_api_key='neshan-new', payment_provider='zarinpal')
        self.assertEqual(self._value('neshan_api_key'), 'neshan-new')
        self.assertEqual(self._value('payment_provider'), 'internal')
        self.assertEqual(list(SettingChangeRequest.objects.get().changes), ['payment_provider'])

    def test_saving_again_updates_the_same_request(self):
        self._submit(payment_provider='zarinpal')
        self._submit(payment_provider='jibit')
        self.assertEqual(SettingChangeRequest.objects.get().changes['payment_provider']['value'], 'jibit')
        self._submit()
        self.assertFalse(SettingChangeRequest.objects.exists())

    def test_admin_approval_applies_and_wipes_the_secret(self):
        self._submit(payment_api_key=SECRET, payment_provider='zarinpal')
        change = SettingChangeRequest.objects.get()
        self.client.force_login(self.admin)
        page = self.client.get(reverse('core:setting-approvals'))
        self.assertContains(page, 'زرین')
        self.assertNotContains(page, SECRET)
        self.client.post(reverse('core:setting-approval-decide', args=[change.pk, 'approve']))
        self.assertEqual(self._value('payment_api_key'), SECRET)
        self.assertEqual(self._value('payment_provider'), 'zarinpal')
        change.refresh_from_db()
        self.assertEqual(change.status, 'approved')
        self.assertEqual(change.changes['payment_api_key']['value'], '')
        self.assertEqual(change.decided_by, self.admin)

    def test_rejection_changes_nothing_and_cannot_be_reversed(self):
        self._submit(payment_provider='zarinpal')
        change = SettingChangeRequest.objects.get()
        self.client.force_login(self.admin)
        self.client.post(reverse('core:setting-approval-decide', args=[change.pk, 'reject']))
        self.client.post(reverse('core:setting-approval-decide', args=[change.pk, 'approve']))
        self.assertEqual(self._value('payment_provider'), 'internal')
        change.refresh_from_db()
        self.assertEqual(change.status, 'rejected')

    def test_admin_saves_directly(self):
        self.client.force_login(self.admin)
        self._submit(payment_api_key='old-payment', payment_provider='zarinpal')
        self.assertEqual(self._value('payment_provider'), 'zarinpal')
        self.assertFalse(SettingChangeRequest.objects.exists())

    def test_technical_cannot_decide(self):
        self._submit(payment_provider='zarinpal')
        change = SettingChangeRequest.objects.get()
        self.assertEqual(self.client.get(reverse('core:setting-approvals')).status_code, 403)
        url = reverse('core:setting-approval-decide', args=[change.pk, 'approve'])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self._value('payment_provider'), 'internal')

    def test_parameters_page_is_no_side_door(self):
        param = SystemParameter.objects.get(key='payment_provider')
        self.assertEqual(self.client.get(reverse('core:parameters-edit', args=[param.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('core:parameters-delete', args=[param.pk])).status_code, 403)
        self.client.post(reverse('core:parameters-create'), {'key': 'sms_provider', 'value': 'http'})
        self.assertFalse(SystemParameter.objects.filter(key='sms_provider').exists())
        other = SystemParameter.objects.create(key='plain', value='1')
        self.client.post(reverse('core:parameters-edit', args=[other.pk]), {'key': 'SMS_sender', 'value': '1'})
        other.refresh_from_db()
        self.assertEqual(other.key, 'plain')


class InverterMonitoringTests(TestCase):
    def setUp(self):
        self.tech = User.objects.create_user('tech', password='x', role='technical')
        customer = User.objects.create_user('cust', password='x', role='customer')
        self.plant = Plant.objects.create(
            name='یزد', owner=customer, external_code='Y1', location_name='یزد',
            latitude=Decimal('31.9'), longitude=Decimal('54.3'), capacity_kw=Decimal('200'))
        self.inverter = Inverter.objects.create(plant=self.plant, serial_number='SN1', model_name='X3',
                                                rated_power_kw=100, online=True)
        self.client.force_login(self.tech)

    def _reading(self, power='42.5', energy='7.5'):
        return TelemetryReading.objects.create(
            plant=self.plant, inverter=self.inverter, power_kw=Decimal(power), voltage_v=230,
            current_a=10, frequency_hz=50, energy_kwh=Decimal(energy))

    def _row(self):
        return self.client.get(reverse('plants:inverters')).context['object_list'][0]

    def test_fresh_reading_shows_power_and_todays_energy(self):
        self._reading()
        self._reading(power='50', energy='2.5')
        row = self._row()
        self.assertEqual(row.state_label, 'متصل')
        self.assertTrue(row.is_fresh)
        self.assertEqual(row.live_power, Decimal('50'))
        self.assertEqual(row.today_kwh, Decimal('10'))

    def test_old_reading_is_not_shown_as_current_power(self):
        reading = self._reading()
        TelemetryReading.objects.filter(pk=reading.pk).update(created_at=timezone.now() - timedelta(hours=2))
        row = self._row()
        self.assertEqual(row.state_label, 'داده قدیمی')
        self.assertFalse(row.is_fresh)

    def test_sync_error_and_no_data_are_stated(self):
        self.assertEqual(self._row().state_label, 'بدون داده')
        Inverter.objects.filter(pk=self.inverter.pk).update(last_sync_error='err')
        self.assertEqual(self._row().state_label, 'خطا در دریافت')
