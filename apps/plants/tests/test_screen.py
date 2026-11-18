"""The plant's live screen."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.plants.models import Inverter, Plant, PlantSection, PlantTariff, TelemetryReading
from apps.plants.screen import build_screen

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver'])
class ScreenTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = User.objects.create_user('screen-owner', password='x', role='customer')
        self.plant = Plant.objects.create(name='یزد', owner=self.customer, external_code='S1', location_name='یزد',
                                          latitude=Decimal('31.9'), longitude=Decimal('54.3'), capacity_kw=Decimal('200'))
        now = timezone.now()
        self.inverter = Inverter.objects.create(
            plant=self.plant, serial_number='SN', model_name='X3', rated_power_kw=Decimal('125'), last_synced_at=now,
            last_daily_yield_kwh=Decimal('50'), latest_data={'total_yield_kwh': 1000, 'dc_kw': 62, 'temperature_c': 40})
        PlantSection.objects.create(plant=self.plant, name='سوله ۱', inverter=self.inverter, blocks='10x10', panel_watt=500)
        PlantSection.objects.create(plant=self.plant, name='سوله ۲', blocks='10x2', panel_watt=500)
        PlantTariff.objects.create(plant=self.plant, rate_rial_per_kwh=Decimal('10000'),
                                   valid_from=timezone.localdate() - timedelta(days=40))
        TelemetryReading.objects.create(plant=self.plant, inverter=self.inverter, power_kw=Decimal('25'), voltage_v=0,
                                        current_a=0, frequency_hz=0, energy_kwh=Decimal('50'), status='normal')

    def test_payload_joins_live_income_impact_and_unmonitored_sections(self):
        data = build_screen(self.plant)
        self.assertEqual(data['status']['tone'], 'ok')
        self.assertEqual((data['live']['power'], data['live']['percent']), ('۲۵٫۰', 50))
        self.assertEqual(data['today']['kwh'], '۵۰٫۰')
        self.assertEqual(data['today']['hours'], '۱٫۰۰')
        self.assertEqual(data['today']['toman'], '۵۰٬۰۰۰')
        self.assertEqual(data['impact'][0]['value'], '۵۹۹')
        self.assertEqual(data['unmonitored'][0]['name'], 'سوله ۲')
        self.assertEqual(sum(data['energy']['week']['kwh']), 50)
        self.assertEqual(data['energy']['week']['toman'][-1], 50000)
        self.assertEqual(len(data['energy']['month']['labels']), 30)

    def test_stale_data_is_not_called_live(self):
        TelemetryReading.objects.update(created_at=timezone.now() - timedelta(hours=2))
        data = build_screen(self.plant)
        self.assertEqual(data['status']['tone'], 'warn')
        self.assertFalse(data['live']['active'])
        self.assertEqual(data['live']['power'], '—')

    def test_access_follows_the_plant(self):
        url = reverse('plants:screen-data', args=[self.plant.pk])
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(url, **HOST).status_code, 200)
        self.assertContains(self.client.get(reverse('plants:screen'), **HOST), 'data-screen-url')
        self.client.force_login(User.objects.create_user('stranger', password='x', role='customer'))
        self.assertEqual(self.client.get(url, **HOST).status_code, 404)
