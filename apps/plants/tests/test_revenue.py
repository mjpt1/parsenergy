"""Plant income, and the real roof layout that replaces the placeholder grid."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.localtime import day_start
from apps.plants.forms import PlantSectionForm
from apps.plants.layout import module_grid_payload
from apps.plants import solax
from apps.plants.monitor import build_monitor
from apps.plants.models import Inverter, InverterSample, Plant, PlantBill, PlantSection, PlantTariff, TelemetryReading
from apps.plants.revenue import build_revenue, custom_period, jalali_text, parse_jalali

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user('cust', password='x', role='customer')
        self.admin = User.objects.create_user('boss', password='x', role='admin')
        self.plant = Plant.objects.create(
            name='یزد', owner=self.customer, external_code='Y1', location_name='یزد',
            latitude=Decimal('31.9'), longitude=Decimal('54.3'), capacity_kw=Decimal('200'))
        self.inverter = Inverter.objects.create(plant=self.plant, serial_number='SN1', model_name='X3',
                                                rated_power_kw=125, online=True)
        self.today = timezone.localdate()

    def reading(self, energy, moment=None, power='50'):
        row = TelemetryReading.objects.create(
            plant=self.plant, inverter=self.inverter, power_kw=Decimal(power), voltage_v=230,
            current_a=10, frequency_hz=50, energy_kwh=Decimal(energy))
        if moment is not None:
            TelemetryReading.objects.filter(pk=row.pk).update(created_at=moment)
        return row

    def rate(self, value, day):
        return PlantTariff.objects.create(plant=self.plant, rate_rial_per_kwh=Decimal(value), valid_from=day)

    def period(self, key):
        return next(p for p in build_revenue(self.plant)['periods'] if p['key'] == key)


class RevenueTests(Base):
    def test_each_day_uses_its_own_rate(self):
        yesterday = self.today - timedelta(days=1)
        self.rate('10000', yesterday)
        self.rate('20000', self.today)
        self.reading('10', day_start(yesterday) + timedelta(hours=10))
        self.reading('5')
        self.assertEqual(self.period('yesterday')['toman'], Decimal('10000'))
        self.assertEqual(self.period('today')['toman'], Decimal('10000'))
        self.assertEqual(self.period('all')['toman'], Decimal('20000'))

    def test_production_before_the_first_rate_is_not_priced(self):
        self.rate('10000', self.today)
        self.reading('7', day_start(self.today - timedelta(days=3)))
        self.reading('1')
        total = self.period('all')
        self.assertEqual(total['toman'], Decimal('1000'))
        self.assertEqual(total['unpriced_text'], '۷٫۰')

    def test_live_income_uses_current_power_and_ignores_old_data(self):
        self.rate('10000', self.today)
        self.reading('1', power='60')
        self.assertEqual(build_revenue(self.plant)['now_toman_text'], '۶۰٬۰۰۰')
        TelemetryReading.objects.update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(build_revenue(self.plant)['now_toman_text'], '—')

    def test_custom_range_includes_both_end_days(self):
        self.rate('10000', self.today - timedelta(days=5))
        self.reading('2', day_start(self.today - timedelta(days=2)) + timedelta(hours=23))
        self.reading('3', day_start(self.today - timedelta(days=1)))
        day = self.today - timedelta(days=2)
        self.assertEqual(custom_period(self.plant, day, day)['toman'], Decimal('2000'))

    def test_jalali_date_round_trip(self):
        self.assertEqual(parse_jalali(jalali_text(self.today)), self.today)
        with self.assertRaises(ValueError):
            parse_jalali('1405/13/01')


class RevenueAccessTests(Base):
    def setUp(self):
        super().setUp()
        self.rate('49832', self.today)
        self.reading('10')
        self.data_url = reverse('plants:revenue-data', args=[self.plant.pk])

    def test_customer_sees_income_on_dashboard_and_page(self):
        self.client.force_login(self.customer)
        self.assertContains(self.client.get(reverse('dashboard')), 'درآمد همین لحظه')
        page = self.client.get(reverse('plants:revenue'))
        self.assertContains(page, '۴۹٬۸۳۲')
        self.assertNotContains(page, 'ثبت نرخ')
        self.assertEqual(self.client.get(self.data_url).status_code, 200)

    def test_other_customer_is_refused(self):
        self.client.force_login(User.objects.create_user('other', password='x', role='customer'))
        self.assertEqual(self.client.get(self.data_url).status_code, 404)

    def test_finance_and_technical_see_every_plant(self):
        for role in ('financial', 'technical', 'operations'):
            self.client.force_login(User.objects.create_user(role, password='x', role=role))
            self.assertEqual(self.client.get(self.data_url).status_code, 200, role)

    def test_only_management_sets_rates(self):
        url = reverse('plants:revenue-rate', args=[self.plant.pk])
        body = {'rate': '۵۹٬۷۸۱', 'valid_from': jalali_text(self.today + timedelta(days=1))}
        self.client.force_login(User.objects.create_user('t', password='x', role='technical'))
        self.assertEqual(self.client.post(url, body).status_code, 403)
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(url, body).status_code, 403)
        self.assertEqual(PlantTariff.objects.count(), 1)
        self.client.force_login(self.admin)
        self.client.post(url, body)
        self.assertEqual(PlantTariff.objects.get(valid_from=self.today + timedelta(days=1)).rate_rial_per_kwh, 59781)
        self.assertEqual(build_revenue(self.plant)['rate_toman_text'], '۴٬۹۸۳٫۲')

    def test_bad_rate_is_rejected(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('plants:revenue-rate', args=[self.plant.pk]),
                         {'rate': '-1', 'valid_from': jalali_text(self.today)})
        self.assertEqual(PlantTariff.objects.count(), 1)

    def test_no_rate_hides_customer_panel(self):
        PlantTariff.objects.all().delete()
        self.client.force_login(self.customer)
        self.assertNotContains(self.client.get(reverse('dashboard')), 'درآمد همین لحظه')


class SectionLayoutTests(Base):
    def setUp(self):
        super().setUp()
        self.section = PlantSection.objects.create(
            plant=self.plant, name='سوله ۱', inverter=self.inverter, blocks='18x5, 18x5, 7x1',
            panel_watt=Decimal('620'), panel_length_m=Decimal('2.382'), panel_width_m=Decimal('1.134'),
            roof_area_m2=Decimal('1163.75'))

    def test_figures_match_the_client_document(self):
        self.assertEqual(self.section.panel_count, 187)
        self.assertEqual(self.section.kwp, Decimal('115.94'))
        self.assertAlmostEqual(float(self.section.panels_area_m2), 505.1, places=1)
        self.assertAlmostEqual(float(self.section.roof_usage_pct), 43.4, places=1)
        self.assertEqual(self.plant.active_capacity_kw, Decimal('115.94'))

    def _status(self):
        return module_grid_payload(self.plant)['sections'][0]

    def test_panels_follow_the_inverter(self):
        self.assertEqual(self._status()['status'], 'offline')
        self.reading('1', power='62')
        section = self._status()
        self.assertEqual((section['status'], section['average_w']), ('ok', 332))
        self.assertEqual(module_grid_payload(self.plant)['summary']['ok'], 187)
        self.reading('0', power='0')
        self.assertEqual(self._status()['status'], 'idle')
        Inverter.objects.filter(pk=self.inverter.pk).update(status='fault', online=False)
        self.section.refresh_from_db()
        self.assertEqual(self._status()['status'], 'fault')

    def test_unconnected_roof_is_marked_and_not_counted_as_connected(self):
        PlantSection.objects.create(plant=self.plant, name='سوله ۳', blocks='27x2, 26x1', panel_watt=620)
        data = module_grid_payload(self.plant)
        self.assertEqual(data['sections'][1]['status'], 'pending')
        self.assertEqual(data['summary']['pending'], 80)
        self.assertEqual(data['connected_kw'], 115.94)

    def test_plant_without_sections_keeps_the_old_grid(self):
        self.section.delete()
        self.assertNotIn('sections', module_grid_payload(self.plant))

    def test_form_checks_blocks_and_inverter_owner(self):
        other = Plant.objects.create(name='ب', owner=self.customer, external_code='Y2', location_name='x',
                                     latitude=1, longitude=1, capacity_kw=1)
        form = PlantSectionForm({'plant': other.pk, 'name': 'x', 'inverter': self.inverter.pk,
                                 'blocks': 'abc', 'panel_watt': '620', 'sort_order': 0})
        self.assertFalse(form.is_valid())
        self.assertIn('blocks', form.errors)
        self.assertIn('inverter', form.errors)

    def test_section_pages_are_for_management_and_technical(self):
        url = reverse('plants:sections')
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(User.objects.create_user('t', password='x', role='technical'))
        self.assertContains(self.client.get(url), 'سوله ۱')
        self.assertEqual(self.client.get(reverse('plants:section-create')).status_code, 200)


class BillTests(Base):
    def setUp(self):
        super().setUp()
        self.url = reverse('plants:bills')
        self.save_url = reverse('plants:bill-save', args=[self.plant.pk])
        self.body = {'period_start': '۱۴۰۵/۰۶/۰۱', 'period_end': '۱۴۰۵/۰۷/۰۱', 'energy_kwh': '۳۴٬۶۴۰',
                     'benchmark_kwh': '73361', 'income_rial': '2,121,004,186', 'balance_rial': '0',
                     'net_rial': '2121004186', 'file_number': '۷۰۵۴۵۲', 'customer_name': 'نمونه'}

    def test_admin_records_and_customer_sees_the_statement(self):
        self.client.force_login(self.admin)
        self.client.post(self.save_url, self.body)
        bill = PlantBill.objects.get()
        self.assertEqual((bill.energy_kwh, bill.income_rial, bill.file_number), (34640, 2121004186, '705452'))
        self.client.force_login(self.customer)
        page = self.client.get(self.url, {'plant': self.plant.pk, 'mode': 'month'})
        self.assertContains(page, '۲٬۱۲۱٬۰۰۴٬۱۸۶')
        self.assertContains(page, '۴۷٫۲')
        self.assertContains(page, '۱۴۰۵/۰۶')
        self.assertNotContains(page, 'ثبت صورتحساب')
        self.assertContains(self.client.get(reverse('dashboard')), 'آخرین صورتحساب')

    def test_only_management_records_and_others_cannot_read(self):
        self.client.force_login(self.customer)
        self.assertEqual(self.client.post(self.save_url, self.body).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(self.save_url, self.body)
        self.client.force_login(User.objects.create_user('other', password='x', role='customer'))
        self.assertNotContains(self.client.get(self.url, {'plant': self.plant.pk}), '۲٬۱۲۱٬۰۰۴٬۱۸۶')

    def test_reversed_dates_are_refused(self):
        self.client.force_login(self.admin)
        self.client.post(self.save_url, {**self.body, 'period_end': '۱۴۰۵/۰۵/۰۱'})
        self.assertFalse(PlantBill.objects.exists())


class InverterDetailTests(Base):
    ROW = {'devicesn': 'SN1', 'totalactivepower': 60, 'dailyyield': 10, 'totalyield': 48061.4, 'devicestatus': 102,
           'invertertemperature': 41.5, 'totalpowerfactor': 0.99, 'gridfrequency': 49.9,
           'acvoltage1': 230, 'accurrent1': 87, 'acvoltage2': 231, 'accurrent2': 86,
           'mpptmap': {'MPPT1Voltage': 700, 'MPPT1Current': 20, 'MPPT2Voltage': 650, 'MPPT2Current': 10},
           'pvmap': {'PV1Voltage': 700, 'PV1Current': 10}}

    def test_cloud_detail_is_kept_and_shown_to_the_owner(self):
        solax.store_reading(self.inverter, {k.lower(): v for k, v in self.ROW.items()})
        self.inverter.refresh_from_db()
        self.assertEqual(self.inverter.latest_data['dc_kw'], 20.5)
        self.assertEqual(self.inverter.latest_data['mppt'][1]['kw'], 6.5)
        url = reverse('plants:inverter-detail', args=[self.inverter.pk])
        self.client.force_login(self.customer)
        page = self.client.get(url)
        self.assertContains(page, 'دمای اینورتر')
        self.assertContains(page, 'ورودی‌های MPPT')
        self.client.force_login(User.objects.create_user('other', password='x', role='customer'))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_missing_maps_do_not_break_the_snapshot(self):
        data = solax.detail_snapshot({'mpptmap': None, 'pvmap': 'x'})
        self.assertEqual((data['mppt'], data['pv'], data['dc_kw']), ([], [], None))


class MonitorTests(InverterDetailTests):
    def setUp(self):
        super().setUp()
        self.rate('10000', self.today)
        solax.store_reading(self.inverter, {k.lower(): v for k, v in self.ROW.items()})
        self.inverter.refresh_from_db()

    def test_every_number_is_kept_and_history_grows(self):
        self.assertEqual(self.inverter.latest_data['fields']['invertertemperature'], 41.5)
        self.assertEqual(self.inverter.latest_data['fields']['mppt1voltage'], 700)
        sample = InverterSample.objects.get()
        self.assertNotIn('fields', sample.data)
        self.assertEqual(sample.data['temperature_c'], 41.5)

    def test_monitor_lists_charts_cards_and_fields(self):
        data = build_monitor(self.plant, '7')
        block = data['inverters'][0]
        titles = {chart['title'] for chart in block['charts']}
        self.assertTrue({'توان خروجی', 'دمای اینورتر', 'ولتاژ فازها', 'توان ورودی‌های MPPT'} <= titles)
        self.assertEqual(len(data['daily']), 2)
        self.assertEqual(len(data['daily'][0]['labels']), 7)
        self.assertEqual(data['daily'][1]['series'][0]['data'][-1], 10000)
        labels = {item['label'] for group in block['fields'] for item in group['items']}
        self.assertIn('دمای اینورتر', labels)
        self.assertTrue(block['fresh'])

    def test_impossible_efficiency_is_not_shown(self):
        cards = {c['label']: c['value'] for c in build_monitor(self.plant)['inverters'][0]['cards']}
        self.assertEqual(cards['بازده تبدیل'], '—')   # 60 kW out from 20.5 kW in

    def test_monitor_access_follows_the_plant(self):
        url = reverse('plants:monitor-data', args=[self.plant.pk])
        self.client.force_login(self.customer)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertContains(self.client.get(reverse('plants:monitor')), 'data-monitor-url')
        self.client.force_login(User.objects.create_user('tech2', password='x', role='technical'))
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(User.objects.create_user('other', password='x', role='customer'))
        self.assertEqual(self.client.get(url).status_code, 404)
