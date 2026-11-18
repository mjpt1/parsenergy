import base64
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.core.models import SystemParameter

User = get_user_model()
HOST = {'HTTP_HOST': 'localhost'}


def fake_jwt(exp: int) -> str:
    """A made-up JWT-shaped key with the given expiry (not a real map.ir key)."""
    def part(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip('=')
    return f"{part({'alg': 'none'})}.{part({'exp': exp, 'scopes': ['basic']})}.sig"


class MapKeySettingTests(TestCase):
    def setUp(self):
        User.objects.create_user(username='su', password='p', is_superuser=True, is_staff=True)
        self.client.login(username='su', password='p')
        self.url = reverse('core:integration-settings')

    def test_page_has_map_key_field(self):
        resp = self.client.get(self.url, **HOST)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="map_api_key"')

    def test_saving_stores_key_and_shows_expiry(self):
        key = fake_jwt(1794986396)  # 2026-11-18
        form = self.client.get(self.url, **HOST).context['form']
        data = {k: v for k, v in form.initial.items() if v not in (None, False)}
        data.update({'map_api_key': f'  {key}  ', 'sms_provider': 'console',
                     'shahkar_provider': 'mock', 'payment_provider': 'internal'})
        self.client.post(self.url, data, **HOST)
        self.assertEqual(SystemParameter.objects.get(key='map_api_key').value, key)
        resp = self.client.get(self.url, **HOST)
        self.assertEqual(resp.context['map_key_expiry'].year, 2026)
        self.assertEqual(resp.context['map_key_expiry'].month, 11)
