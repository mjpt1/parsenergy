from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.plants.models import Equipment, Plant


def _plant(owner, code):
    return Plant.objects.create(
        name=f'Plant {code}',
        owner=owner,
        external_code=code,
        location_name='Tehran',
        latitude='35.689200',
        longitude='51.389000',
        capacity_kw='100.00',
    )


class ApiScopeWriteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='owner', password='password123', role='owner')
        self.other = User.objects.create_user(username='other', password='password123', role='owner')
        self.owner_plant = _plant(self.owner, 'OWNER-001')
        self.other_plant = _plant(self.other, 'OTHER-001')
        self.owner_equipment = Equipment.objects.create(
            plant=self.owner_plant,
            category=Equipment.Category.INVERTER,
            name='Owner Inverter',
            serial_number='OWN-INV',
        )
        self.other_equipment = Equipment.objects.create(
            plant=self.other_plant,
            category=Equipment.Category.INVERTER,
            name='Other Inverter',
            serial_number='OTH-INV',
        )
        self.client.login(username='owner', password='password123')

    def test_non_admin_plant_create_is_assigned_to_request_user(self):
        response = self.client.post(
            '/api/plants/',
            {
                'name': 'New Plant',
                'external_code': 'NEW-001',
                'location_name': 'Shiraz',
                'latitude': '29.591800',
                'longitude': '52.583700',
                'capacity_kw': '50.00',
                'owner': self.other.id,
            },
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Plant.objects.filter(external_code='NEW-001').exists())

        response = self.client.post(
            '/api/plants/',
            {
                'name': 'New Plant',
                'external_code': 'NEW-001',
                'location_name': 'Shiraz',
                'latitude': '29.591800',
                'longitude': '52.583700',
                'capacity_kw': '50.00',
            },
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Plant.objects.get(external_code='NEW-001').owner, self.owner)

    def test_non_admin_cannot_create_equipment_under_other_plant(self):
        response = self.client.post(
            '/api/inverters/',
            {
                'plant': self.other_plant.id,
                'serial_number': 'INV-X',
                'model_name': 'Model X',
                'status': 'online',
                'online': True,
                'rated_power_kw': '10.00',
            },
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 400)

    def test_measurement_equipment_must_belong_to_selected_plant(self):
        response = self.client.post(
            '/api/realtime-measurements/',
            {
                'plant': self.owner_plant.id,
                'equipment': self.other_equipment.id,
                'parameter': 'power',
                'value': '12.5',
                'unit': 'kW',
                'quality': 'good',
            },
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 400)

    def test_measurement_can_be_created_for_scoped_plant_and_equipment(self):
        response = self.client.post(
            '/api/realtime-measurements/',
            {
                'plant': self.owner_plant.id,
                'equipment': self.owner_equipment.id,
                'parameter': 'power',
                'value': '12.5',
                'unit': 'kW',
                'quality': 'good',
            },
            content_type='application/json',
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 201)
