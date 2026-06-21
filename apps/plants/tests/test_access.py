from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.plants.models import Plant, PlantGroup, PlantMembership


class PlantAccessTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username='owner',
            password='password123',
            role='owner',
        )
        self.other_owner = get_user_model().objects.create_user(
            username='other',
            password='password123',
            role='owner',
        )
        self.member_user = get_user_model().objects.create_user(
            username='member',
            password='password123',
            role='owner',
        )

        self.owner_plant = Plant.objects.create(
            name='Owner Plant',
            owner=self.owner,
            external_code='OWNER-PLANT',
            location_name='Tehran',
            latitude=35.6892,
            longitude=51.3890,
            capacity_kw=10.0,
            timezone='Asia/Tehran',
        )
        self.other_plant = Plant.objects.create(
            name='Other Plant',
            owner=self.other_owner,
            external_code='OTHER-PLANT',
            location_name='Tehran',
            latitude=35.6892,
            longitude=51.3890,
            capacity_kw=12.0,
            timezone='Asia/Tehran',
        )
        PlantMembership.objects.create(
            plant=self.other_plant,
            user=self.member_user,
            access_level='viewer',
            active=True,
        )

        self.other_group = PlantGroup.objects.create(
            name='Other Group',
            owner=self.other_owner,
            description='Should be inaccessible to member',
        )

    def test_member_can_access_shared_plant_via_owner_dashboard(self):
        self.client.login(username='member', password='password123')
        response = self.client.get(reverse('core:owner-dashboard-data'), HTTP_HOST='localhost')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['plant_count'], 1)
