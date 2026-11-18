from django.test import TestCase

from apps.requests.todo import build_todo


class TodoTests(TestCase):
    def test_only_nonzero_items_overdue_first(self):
        stats = {'overdue': 2, 'needs_contact': 0, 'in_technical': 5, 'unassigned_sales': 0, 'sla_hours': 72}
        fleet = {'offline': 0, 'alerts': 1}
        items = build_todo('admin', stats, fleet, None)
        texts = [i['text'] for i in items]
        self.assertEqual(texts[0], 'درخواست از مهلت پیگیری گذشته')
        self.assertIn('درخواست منتظر پیشنهاد فنی', texts)
        self.assertNotIn('مشتری منتظر تماس فروش', texts)
        self.assertTrue(all(i['n'] for i in items))

    def test_technical_points_at_its_queue(self):
        items = build_todo('technical', {'in_technical': 3}, {'offline': 1, 'alerts': 0, 'hot_cells': 0}, None)
        self.assertEqual(items[0]['text'], 'نیروگاه قطع است')
        self.assertIn('department=technical', items[1]['url'])


class RequestListOnPhoneTests(TestCase):
    def test_list_has_card_labels_and_counts_filters(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse
        admin = get_user_model().objects.create_user('list-admin', password='x', role='admin')
        self.client.force_login(admin)
        page = self.client.get(reverse('requests:admin-list'), {'q': 'x', 'page': '1', 'priority': 'high', 'date_from': ''})
        self.assertContains(page, 'data-filter-toggle')
        self.assertContains(page, 'req-table')
        self.assertContains(page, 'فیلترها (1)')
