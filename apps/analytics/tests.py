import io
import json
import urllib.error
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.core import ai
from apps.core.models import SystemParameter
from apps.requests.services import lifecycle

from . import traffic
from .models import Visit

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}
UA = {'HTTP_USER_AGENT': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile Safari'}


def _param(**values):
    for k, v in values.items():
        SystemParameter.objects.update_or_create(key=k, defaults={'value': v})


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _answer(text):
    return _Resp(json.dumps({'choices': [{'message': {'content': text}}]}).encode())


class ClassifyTests(TestCase):
    def test_sources(self):
        self.assertEqual(traffic.classify('/', 'www.google.com', ''), Visit.Source.GOOGLE)
        self.assertEqual(traffic.classify('/', 'l.instagram.com', ''), Visit.Source.INSTAGRAM)
        self.assertEqual(traffic.classify('/', 'pars-energy.com', ''), Visit.Source.MAIN_SITE)
        self.assertEqual(traffic.classify('/leads/go/abc/', '', ''), Visit.Source.QR)
        self.assertEqual(traffic.classify('/leads/f/abc/', '', ''), Visit.Source.SMS)
        self.assertEqual(traffic.classify('/', '', 'newsletter'), Visit.Source.CAMPAIGN)
        self.assertEqual(traffic.classify('/', '', 'instagram'), Visit.Source.INSTAGRAM)
        self.assertEqual(traffic.classify('/', 'example.org', ''), Visit.Source.OTHER_SITE)
        self.assertEqual(traffic.classify('/', '', ''), Visit.Source.DIRECT)


class TrackingTests(TestCase):
    def test_public_visit_recorded_once(self):
        self.client.get('/card/', HTTP_REFERER='https://www.google.com/', **HOST, **UA)
        self.client.get('/card/', HTTP_REFERER='https://www.google.com/', **HOST, **UA)
        self.assertEqual(Visit.objects.count(), 1)
        v = Visit.objects.get()
        self.assertEqual((v.source, v.device, v.path), ('google', 'mobile', '/card/'))

    def test_internal_navigation_staff_and_bots_skipped(self):
        self.client.get('/card/', HTTP_REFERER='http://localhost/requests/submit/', **HOST, **UA)
        self.client.get('/card/', HTTP_USER_AGENT='Googlebot/2.1', **HOST)
        User.objects.create_user(username='s', password='p', role='sales')
        self.client.login(username='s', password='p')
        self.client.get('/card/', **HOST, **UA)
        self.assertEqual(Visit.objects.count(), 0)

    def test_pixel_records_main_site_visit(self):
        resp = self.client.get(reverse('analytics:pixel'),
                               {'p': '/blog/x', 'r': 'https://t.me/foo'}, **HOST, **UA)
        self.assertEqual(resp['Content-Type'], 'image/gif')
        v = Visit.objects.get()
        self.assertEqual((v.host, v.path, v.source), ('pars-energy.com', '/blog/x', 'telegram'))


class TrafficReportTests(TestCase):
    def test_sales_can_view_technical_cannot(self):
        Visit.objects.create(visitor_id='a' * 32, path='/card/', source='google')
        User.objects.create_user(username='s', password='p', role='sales')
        User.objects.create_user(username='t', password='p', role='technical')
        self.client.login(username='s', password='p')
        resp = self.client.get(reverse('analytics:traffic'), **HOST)
        self.assertContains(resp, 'گوگل')
        self.client.login(username='t', password='p')
        self.assertEqual(self.client.get(reverse('analytics:traffic'), **HOST).status_code, 403)


class ProviderFallbackTests(TestCase):
    def test_falls_back_to_gapgpt_then_reports_provider(self):
        _param(ai_enabled='true', ai_base_url='https://api.openai.com/v1', ai_model='m',
               ai_api_key='k', ai_gapgpt_key='g')

        def opener(req, timeout=None):
            if 'openai.com' in req.full_url:
                raise urllib.error.URLError('blocked')
            self.assertIn('api.gapgpt.app/v1/chat/completions', req.full_url)
            return _answer('سلام')
        with mock.patch('urllib.request.urlopen', side_effect=opener):
            result = ai.ask('s', 'u')
        self.assertEqual(result.text, 'سلام')
        self.assertIn('GapGPT', result.provider)

    def test_order_puts_avalai_first(self):
        _param(ai_gapgpt_key='g', ai_avalai_key='a', ai_order='avalai')
        self.assertEqual([p.name for p in ai.providers()], ['avalai', 'gapgpt'])

    def test_no_provider_raises(self):
        with self.assertRaises(ai.AIError):
            ai.ask('s', 'u')


class AITaskTests(TestCase):
    def setUp(self):
        _param(ai_gapgpt_key='g')
        self.admin = User.objects.create_user(username='a', password='p', role='admin')
        self.client.login(username='a', password='p')

    def test_lead_analysis(self):
        req = lifecycle.create_request(full_name='علی', mobile='09120000001', province='تهران')
        with mock.patch('urllib.request.urlopen', return_value=_answer('سرنخ گرم')) as call:
            resp = self.client.post(reverse('analytics:ai-task'),
                                    {'task': 'lead', 'target': req.id}, **HOST)
        self.assertEqual(resp.json()['text'], 'سرنخ گرم')
        prompt = json.loads(call.call_args[0][0].data)['messages'][1]['content']
        self.assertIn('تهران', prompt)

    def test_bad_target_is_404_not_500(self):
        for target in ('', 'abc', '1; drop'):
            resp = self.client.post(reverse('analytics:ai-task'),
                                    {'task': 'lead', 'target': target}, **HOST)
            self.assertEqual(resp.status_code, 404, target)

    def test_customer_cannot_use_tasks(self):
        User.objects.create_user(username='c', password='p')
        self.client.login(username='c', password='p')
        resp = self.client.post(reverse('analytics:ai-task'), {'task': 'lead', 'target': 1}, **HOST)
        self.assertEqual(resp.status_code, 403)


class ChatTests(TestCase):
    def setUp(self):
        cache.clear()

    def _send(self, text):
        return self.client.post(reverse('analytics:ai-chat'),
                                data=json.dumps({'messages': [{'role': 'user', 'content': text}]}),
                                content_type='application/json', **HOST)

    def test_disabled_without_provider(self):
        self.assertEqual(self._send('سلام').status_code, 503)

    def test_answers_and_limits(self):
        _param(ai_avalai_key='a')
        from . import ai_views

        def send(xff):
            return self.client.post(
                reverse('analytics:ai-chat'),
                data=json.dumps({'messages': [{'role': 'user', 'content': 'x'}]}),
                content_type='application/json', HTTP_X_FORWARDED_FOR=xff, **HOST)
        # The host's proxy appends the real address (5.5.5.5) on the right.
        with mock.patch('urllib.request.urlopen', return_value=_answer('درود')):
            self.assertEqual(send('5.5.5.5').json()['text'], 'درود')
        _param(ai_chat_per_visitor='1')
        self.assertEqual(send('5.5.5.5').status_code, 429)
        # A forged left-most entry does not give a fresh limit.
        self.assertEqual(send('9.9.9.9, 5.5.5.5').status_code, 429)

    def test_global_cap(self):
        _param(ai_avalai_key='a', ai_chat_total='5')
        cache.set('ai-chat:all', 5, 3600)
        self.assertEqual(self._send('سلام').status_code, 429)


class FeatureLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        _param(ai_gapgpt_key='g')
        self.req = lifecycle.create_request(full_name='علی', mobile='09120000001', province='تهران')

    def _ask(self, username):
        self.client.login(username=username, password='p')
        return self.client.post(reverse('analytics:ai-task'),
                                {'task': 'lead', 'target': self.req.id}, **HOST)

    def test_role_not_allowed(self):
        User.objects.create_user(username='f', password='p', role='financial')
        self.assertEqual(self._ask('f').status_code, 403)

    def test_feature_switched_off(self):
        User.objects.create_user(username='a', password='p', role='admin')
        _param(ai_feat_lead_enabled='false')
        self.assertEqual(self._ask('a').status_code, 403)

    def test_daily_cap(self):
        User.objects.create_user(username='a', password='p', role='admin')
        _param(ai_feat_lead_daily='1')
        with mock.patch('urllib.request.urlopen', return_value=_answer('ok')):
            self.assertEqual(self._ask('a').status_code, 200)
            self.assertEqual(self._ask('a').status_code, 403)

    def test_settings_page_saves_limits(self):
        User.objects.create_user(username='su', password='p', is_superuser=True, is_staff=True)
        self.client.login(username='su', password='p')
        url = reverse('core:ai-settings')
        form = self.client.get(url, **HOST).context['form']
        data = {}
        for k, v in form.initial.items():
            if v in (None, False):
                continue
            data[k] = v
        data.update({'order': 'primary', 'provider': 'openai-compatible',
                     'feat_lead_roles': ['admin', 'sales'], 'feat_lead_daily': 7,
                     'chat_per_visitor': 10, 'chat_total': 100})
        data.pop('feat_traffic_enabled', None)
        self.client.post(url, data, **HOST)
        from apps.core import ai_limits
        self.assertEqual(ai_limits.settings_for('lead')['roles'], ['admin', 'sales'])
        self.assertEqual(ai_limits.settings_for('lead')['daily'], 7)
        self.assertFalse(ai_limits.settings_for('traffic')['enabled'])
        self.assertEqual(ai_limits.chat_limits(), (10, 100))
