from types import SimpleNamespace as R

from django.test import SimpleTestCase

from apps.requests.progress import customer_progress


def req(status='new', department='marketing', plant_id=None):
    return R(status=status, department=department, plant_id=plant_id)


class CustomerProgressTests(SimpleTestCase):
    def test_new_request_waits_on_staff(self):
        p = customer_progress(req())
        self.assertEqual(p['current'], 'بررسی کارشناسان')
        self.assertFalse(p['your_turn'])
        self.assertEqual([s['state'] for s in p['steps']][:3], ['done', 'now', 'todo'])

    def test_offer_and_contract_are_the_customers_turn(self):
        self.assertTrue(customer_progress(req('offered', 'sales'))['your_turn'])
        self.assertEqual(customer_progress(req('contract_generated', 'sales'))['current'], 'قرارداد')
        self.assertEqual(customer_progress(req('awaiting_payment', 'sales'))['current'], 'پرداخت')

    def test_plant_built_and_stopped_requests(self):
        self.assertTrue(all(s['state'] == 'done' for s in customer_progress(req('paid', 'done', 4))['steps']))
        stopped = customer_progress(req('hold', 'sales'))
        self.assertEqual(stopped['steps'], [])
        self.assertIn('متوقف', stopped['note'])
