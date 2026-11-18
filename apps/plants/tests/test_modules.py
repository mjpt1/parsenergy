from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.plants.layout import ensure_module_grid, module_grid_payload
from apps.plants.models import Plant, PVModule


class PVModuleLayoutTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='cell-owner', password='x', role='owner')
        self.plant = Plant.objects.create(
            name='Cell Plant',
            owner=self.owner,
            external_code='CELL-PLANT',
            location_name='Yazd',
            latitude=Decimal('31.897400'),
            longitude=Decimal('54.356900'),
            capacity_kw=Decimal('50'),
            layout_rows=4,
            layout_cols=6,
        )

    def test_ensure_module_grid_creates_cells(self):
        created = ensure_module_grid(self.plant, seed_temperatures=True)
        self.assertEqual(created, 24)
        self.assertEqual(self.plant.modules.count(), 24)
        payload = module_grid_payload(self.plant)
        self.assertEqual(payload['rows'], 4)
        self.assertEqual(payload['cols'], 6)
        self.assertEqual(payload['summary']['total'], 24)
        # Force at least one hot cell for the heat-map contract.
        hot = self.plant.modules.first()
        hot.temperature_c = Decimal('78')
        hot.status = PVModule.Status.OK
        hot.save()
        payload = module_grid_payload(self.plant)
        self.assertTrue(any(c['status'] == 'hot' for c in payload['cells']))

    def test_temperature_derives_status(self):
        mod = PVModule.objects.create(
            plant=self.plant, row=1, col=1,
            temperature_c=Decimal('76'), status=PVModule.Status.OK,
        )
        mod.refresh_from_db()
        self.assertEqual(mod.status, PVModule.Status.HOT)

    def test_owner_dashboard_includes_module_grid(self):
        ensure_module_grid(self.plant, seed_temperatures=True)
        self.client.force_login(self.owner)
        resp = self.client.get(reverse('dashboard'), HTTP_HOST='localhost')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'pvModuleGrid')
        self.assertContains(resp, 'fleetMap')
