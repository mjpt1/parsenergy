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


class SatelliteTileTests(TestCase):
    """The satellite switch asks the tile proxy for ?theme=satellite."""

    def test_satellite_theme_uses_google_and_jpeg(self):
        from unittest import mock
        from apps.core import tiles
        seen = []

        def fake_fetch(z, x, y, theme=''):
            seen.append(theme)
            return b'\xff\xd8' + b'0' * 2000, 'image/jpeg'
        with mock.patch.object(tiles, 'fetch_tile', side_effect=fake_fetch), \
                mock.patch.object(tiles, 'cached_tile_path') as cp:
            cp.return_value.exists.return_value = False
            resp = self.client.get('/core/tiles/12/2632/1612.png?theme=satellite', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(seen, ['satellite'])
        names = [n for n, _ in tiles.STYLED['satellite']]
        self.assertEqual(names, ['tomtom-satellite', 'google-satellite', 'bing-satellite'])
        self.assertIn('mt1.google.com/vt/lyrs=s', dict(tiles.STYLED['satellite'])['google-satellite'](12, 2632, 1612))

    def test_unknown_theme_falls_back_to_plain(self):
        from unittest import mock
        from apps.core import tiles
        seen = []
        with mock.patch.object(tiles, 'fetch_tile', side_effect=lambda z, x, y, theme='': (seen.append(theme) or (None, ''))), \
                mock.patch.object(tiles, 'cached_tile_path') as cp:
            cp.return_value.exists.return_value = False
            self.client.get('/core/tiles/3/1/1.png?theme=../../etc', HTTP_HOST='localhost')
        self.assertEqual(seen, [''])


class SatelliteFallbackTests(TestCase):
    """TomTom first, then Google, then Bing, then the plain map: always a map."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def _run(self, working, key='k'):
        from unittest import mock
        from apps.core import tiles
        from apps.core.models import SystemParameter
        if key:
            SystemParameter.objects.create(key='map_tomtom_key', value=key)
        asked = []

        def fake_raw(name, build_url, z, x, y):
            asked.append(name)
            if name in working:
                fmt = b'\x89PNG' if not name.endswith('satellite') else b'\xff\xd8'
                return fmt + bytes([z % 250, x % 250, y % 250]) * 400, 'image/x'
            return None, ''
        with mock.patch.object(tiles, '_fetch_raw', side_effect=fake_raw):
            body, _ = tiles.fetch_tile(18, 1, 2, 'satellite')
        return body, asked

    def test_tomtom_first(self):
        body, asked = self._run({'tomtom-satellite', 'google-satellite'})
        self.assertEqual(asked[0], 'tomtom-satellite')
        self.assertNotIn('google-satellite', asked)

    def test_google_when_tomtom_down(self):
        body, asked = self._run({'google-satellite'})
        self.assertIn('google-satellite', asked)
        self.assertTrue(body.startswith(b'\xff\xd8'))

    def test_no_key_skips_tomtom(self):
        body, asked = self._run({'google-satellite'}, key='')
        self.assertNotIn('tomtom-satellite', asked)

    def test_plain_map_when_all_satellite_down(self):
        body, asked = self._run({'mapir'})
        self.assertIn('mapir', asked)
        self.assertTrue(body.startswith(b'\x89PNG'))

    def test_street_fallback_not_cached_as_satellite(self):
        from unittest import mock
        from apps.core import tiles
        with mock.patch.object(tiles, 'fetch_tile', return_value=(b'\x89PNG' + b'0' * 900, 'image/png')), \
                mock.patch.object(tiles, 'cached_tile_path') as cp:
            cp.return_value.exists.return_value = False
            resp = self.client.get('/core/tiles/5/1/1.png?theme=satellite', HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        cp.return_value.write_bytes.assert_not_called()
