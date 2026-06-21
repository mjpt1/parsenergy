from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.views import _build_chart_series_from_measurements
from apps.plants.models import Equipment, Plant, PlantMembership, RealtimeMeasurement


class DashboardDataTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='admin',
            password='password123',
            role='admin',
        )
        self.plant = Plant.objects.create(
            name='Test Solar Plant',
            owner=self.user,
            external_code='TEST-PLANT',
            location_name='Tehran',
            latitude=35.6892,
            longitude=51.3890,
            capacity_kw=100.0,
            timezone='Asia/Tehran',
        )
        self.equipment = Equipment.objects.create(
            plant=self.plant,
            category=Equipment.Category.INVERTER,
            name='Inverter 1',
            serial_number='INV-001',
        )

    def test_chart_series_fallback_uses_last_available_measurement(self):
        timestamp = timezone.now() - timedelta(days=2)
        RealtimeMeasurement.objects.create(
            plant=self.plant,
            equipment=self.equipment,
            parameter='power',
            value=75.5,
            unit='kW',
            quality='good',
            timestamp=timestamp,
        )

        queryset = RealtimeMeasurement.objects.filter(plant=self.plant, parameter='power')
        labels, values = _build_chart_series_from_measurements(queryset, hours=12)

        self.assertEqual(len(labels), 13)
        self.assertEqual(values[-1], 75.5)
        self.assertGreater(sum(values), 0)

    def test_admin_dashboard_data_returns_chart_payload(self):
        timestamp = timezone.now() - timedelta(days=2)
        RealtimeMeasurement.objects.create(
            plant=self.plant,
            equipment=self.equipment,
            parameter='power',
            value=88.0,
            unit='kW',
            quality='good',
            timestamp=timestamp,
        )

        self.client.login(username='admin', password='password123')
        response = self.client.get(reverse('core:admin-dashboard-data'), HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn('chart', data)
        self.assertIn('labels', data['chart'])
        self.assertIn('production', data['chart'])
        self.assertEqual(data['chart']['production'][-1], 88.0)
        self.assertEqual(data['chart']['efficiency'][-1], round((88.0 / float(self.plant.capacity_kw)) * 100, 2))

    def test_owner_dashboard_data_returns_current_power_and_member_plant_count(self):
        member_user = get_user_model().objects.create_user(
            username='member',
            password='memberpass',
            role='owner',
        )
        partner = get_user_model().objects.create_user(
            username='partner',
            password='partnerpass',
            role='owner',
        )
        member_plant = Plant.objects.create(
            name='Shared Plant',
            owner=partner,
            external_code='SHARED-PLANT',
            location_name='Tehran',
            latitude=35.6892,
            longitude=51.3890,
            capacity_kw=50.0,
            timezone='Asia/Tehran',
        )
        PlantMembership.objects.create(
            plant=member_plant,
            user=member_user,
            access_level='viewer',
            active=True,
        )
        RealtimeMeasurement.objects.create(
            plant=member_plant,
            equipment=self.equipment,
            parameter='power',
            value=42.0,
            unit='kW',
            quality='good',
            timestamp=timezone.now(),
        )

        self.client.login(username='member', password='memberpass')
        response = self.client.get(reverse('core:owner-dashboard-data'), HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data['plant_count'], 1)
        self.assertEqual(data['latest_power_kw'], 42.0)
        self.assertIn('chart', data)
        self.assertEqual(data['chart']['production'][-1], 42.0)
