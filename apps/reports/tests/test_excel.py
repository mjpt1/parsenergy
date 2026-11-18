import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from openpyxl import load_workbook

from apps.plants.models import Inverter, Plant, TelemetryReading


class PerformanceWorkbookTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='09120000000', password='x-Pass-123')
        self.plant = Plant.objects.create(name='یزد', owner=self.owner, external_code='YZ-1', location_name='یزد',
                                          latitude=31.9, longitude=54.2, capacity_kw=Decimal('200'))
        inv = Inverter.objects.create(plant=self.plant, serial_number='SN1', model_name='X3', rated_power_kw=125)
        now = timezone.now()
        for back in range(3):
            r = TelemetryReading.objects.create(plant=self.plant, inverter=inv, power_kw=60 + back, voltage_v=230,
                                                current_a=90, frequency_hz=50, energy_kwh=Decimal('100'))
            TelemetryReading.objects.filter(pk=r.pk).update(created_at=now - timedelta(days=back))

    def test_owner_downloads_full_workbook(self):
        self.client.force_login(self.owner)
        resp = self.client.get(f'/reports/{self.plant.id}/excel/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn("filename*=utf-8''", resp['Content-Disposition'])
        wb = load_workbook(io.BytesIO(resp.content))
        self.assertEqual(wb.sheetnames, ['خلاصه عملکرد', 'تولید روزانه', 'پروفایل ساعتی', 'تولید ماهانه',
                                         'اینورترها', 'هشدارها', 'داده خام'])
        summary = wb['خلاصه عملکرد']
        self.assertEqual(summary['B5'].value, 300)                 # 30-day energy card
        self.assertAlmostEqual(summary['E5'].value, 100)           # today... second card is today
        daily = wb['تولید روزانه']
        self.assertEqual(daily['C36'].value, '=SUM(C6:C35)')       # live totals row
        self.assertEqual(len(wb['داده خام']['A']), 5 + 3)

    def test_other_customer_cannot_download(self):
        other = get_user_model().objects.create_user(username='09130000000', password='x-Pass-123')
        self.client.force_login(other)
        self.assertEqual(self.client.get(f'/reports/{self.plant.id}/excel/').status_code, 404)
