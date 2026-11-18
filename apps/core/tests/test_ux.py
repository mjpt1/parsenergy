from datetime import date

from django.test import SimpleTestCase

from apps.core.dates import JalaliDateField, parse_user_date
from apps.core.templatetags.ux_tags import age, fa


class UserDateTests(SimpleTestCase):
    def test_jalali_and_gregorian_forms(self):
        self.assertEqual(parse_user_date('۱۴۰۵/۰۸/۰۱'), date(2026, 10, 23))
        self.assertEqual(parse_user_date('1405-8-1'), date(2026, 10, 23))
        self.assertEqual(parse_user_date('2026-10-23'), date(2026, 10, 23))
        self.assertIsNone(parse_user_date('1405/13/40'))
        self.assertIsNone(parse_user_date('دیروز'))

    def test_form_field_rejects_garbage(self):
        f = JalaliDateField()
        self.assertEqual(f.clean('۱۴۰۵/۰۸/۰۱'), date(2026, 10, 23))
        with self.assertRaises(Exception):
            f.clean('abc')


class UxFilterTests(SimpleTestCase):
    def test_codes_and_ages(self):
        self.assertEqual(fa('normal'), 'عادی')
        self.assertEqual(fa('Critical'), 'بحرانی')
        self.assertEqual(fa('something-else'), 'something-else')
        self.assertEqual(age(3101.5), '۱۲۹ روز')
        self.assertEqual(age(5.2), '۵ ساعت')
        self.assertEqual(age(None), '—')
