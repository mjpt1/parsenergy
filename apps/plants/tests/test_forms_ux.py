"""The shared add/edit/delete pages staff actually use."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.alerts.forms import AlertRuleForm
from apps.alerts.models import AlertRule
from apps.plants.forms import PlantForm
from apps.plants.models import Equipment, Plant

User = get_user_model()


def plant_data(**extra):
    return {
        'name': 'نیروگاه تازه', 'location_name': 'یزد', 'capacity_kw': '100',
        'latitude': '31.9', 'longitude': '54.3', 'connection_status': 'online',
        'protocol': 'modbus', 'layout_rows': '2', 'layout_cols': '2', 'is_active': 'on', **extra,
    }


class PlantOwnerTests(TestCase):
    def setUp(self):
        self.tech = User.objects.create_user('tech', password='x', role='technical')
        self.admin = User.objects.create_user('boss', password='x', role='admin')
        self.customer = User.objects.create_user('cust', password='x', role='customer', phone_number='09120000001')
        self.plant = Plant.objects.create(
            name='یزد', owner=self.customer, external_code='YZ-1', location_name='یزد',
            latitude=Decimal('31.9'), longitude=Decimal('54.3'), capacity_kw=Decimal('200'))

    def test_technician_assigns_a_customer_when_creating(self):
        self.client.force_login(self.tech)
        response = self.client.post(reverse('plants:create'), plant_data(owner=self.customer.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Plant.objects.get(name='نیروگاه تازه').owner, self.customer)

    def test_staff_cannot_be_picked_as_owner_by_a_technician(self):
        form = PlantForm(user=self.tech)
        self.assertEqual(list(form.fields['owner'].queryset), [self.customer])

    def test_owner_may_stay_empty_and_code_is_generated(self):
        self.client.force_login(self.tech)
        self.client.post(reverse('plants:create'), plant_data())
        plant = Plant.objects.get(name='نیروگاه تازه')
        self.assertEqual(plant.owner, self.tech)
        self.assertTrue(plant.external_code.startswith('PLT-'))

    def test_technician_cannot_move_an_existing_plant(self):
        self.client.force_login(self.tech)
        self.client.post(reverse('plants:edit', args=[self.plant.pk]),
                         plant_data(name='یزد', owner=self.tech.pk, external_code='YZ-1'))
        self.plant.refresh_from_db()
        self.assertEqual(self.plant.owner, self.customer)
        self.assertEqual(self.plant.external_code, 'YZ-1')


class SharedPagesTests(TestCase):
    def setUp(self):
        self.tech = User.objects.create_user('tech', password='x', role='technical')
        self.customer = User.objects.create_user('cust', password='x', role='customer')
        self.plant = Plant.objects.create(
            name='یزد', owner=self.customer, external_code='YZ-1', location_name='یزد',
            latitude=Decimal('31.9'), longitude=Decimal('54.3'), capacity_kw=Decimal('200'))
        self.client.force_login(self.tech)

    def test_forms_are_titled_and_labelled_in_persian(self):
        page = self.client.get(reverse('plants:create'))
        self.assertContains(page, 'افزودن نیروگاه')
        self.assertContains(page, 'ظرفیت (کیلووات)')
        self.assertNotContains(page, 'Capacity kw')
        self.assertNotContains(page, 'Timezone')

    def test_equipment_form_no_longer_asks_for_last_contact(self):
        page = self.client.get(reverse('plants:equipment-create'))
        self.assertNotContains(page, 'last_seen_at')

    def test_delete_page_names_what_is_lost(self):
        page = self.client.get(reverse('plants:delete', args=[self.plant.pk]))
        self.assertContains(page, 'حذف نیروگاه')
        self.assertContains(page, 'یزد')
        self.assertContains(page, 'برگشت‌پذیر نیست')
        equipment = Equipment.objects.create(plant=self.plant, category='other', name='تابلو برق')
        self.assertEqual(str(equipment), 'تابلو برق')


class AlertRuleFormTests(TestCase):
    def setUp(self):
        self.tech = User.objects.create_user('tech', password='x', role='technical')
        customer = User.objects.create_user('cust', password='x', role='customer')
        self.plant = Plant.objects.create(
            name='یزد', owner=customer, external_code='YZ-1', location_name='یزد',
            latitude=Decimal('31.9'), longitude=Decimal('54.3'), capacity_kw=Decimal('200'))

    def test_technician_can_watch_a_customer_plant_and_channels_stay_a_list(self):
        form = AlertRuleForm(data={
            'plant': self.plant.pk, 'name': 'ولتاژ بالا', 'metric': 'voltage_v', 'comparator': '>',
            'threshold_value': '250', 'severity': 'high', 'channels': ['sms', 'push'], 'enabled': 'on',
        }, user=self.tech)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().channels, 'sms,push')

    def test_an_older_custom_value_survives_editing(self):
        rule = AlertRule.objects.create(plant=self.plant, name='r', metric='old_metric',
                                        threshold_value=1, channels='email')
        form = AlertRuleForm(instance=rule, user=self.tech)
        self.assertIn('old_metric', dict(form.fields['metric'].choices))
        self.assertEqual(form.initial['channels'], ['email'])
