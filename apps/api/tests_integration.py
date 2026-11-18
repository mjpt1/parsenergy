"""What an outside integration token may and may not do.

The promise made to the customer is narrow and testable: the token sees exactly
what a technical member of staff sees, and it cannot change anything.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.authtoken.models import Token

from apps.requests.models import Request

User = get_user_model()


class IntegrationTokenTests(TestCase):
    def setUp(self):
        self.svc = User.objects.create_user(username='svc-test', role='technical')
        self.token = Token.objects.create(user=self.svc)
        self.auth = {'HTTP_AUTHORIZATION': f'Token {self.token.key}'}
        self.req = Request.objects.create(
            full_name='محمد رضایی', mobile='09121112233', national_id='0012345678',
            province='تهران', city='تهران', description='پروژه تست')

    def test_read_is_allowed(self):
        resp = self.client.get('/api/requests/', **self.auth)
        self.assertEqual(resp.status_code, 200)

    def test_every_write_method_is_refused(self):
        payload = {'full_name': 'نفوذی', 'mobile': '09120000000', 'province': 'تهران'}
        for method, url in (
            (self.client.post, '/api/requests/'),
            (self.client.put, f'/api/requests/{self.req.pk}/'),
            (self.client.patch, f'/api/requests/{self.req.pk}/'),
            (self.client.delete, f'/api/requests/{self.req.pk}/'),
        ):
            resp = method(url, payload, content_type='application/json', **self.auth)
            self.assertEqual(resp.status_code, 403, f'{method.__name__} {url}')
        self.assertTrue(Request.objects.filter(pk=self.req.pk).exists())
        self.assertEqual(Request.objects.count(), 1)

    def test_identity_fields_are_withheld(self):
        """Exactly the technical role's view: no name, no mobile, no owner."""
        resp = self.client.get('/api/requests/', **self.auth)
        body = resp.json()
        rows = body['results'] if isinstance(body, dict) and 'results' in body else body
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn('full_name', row)
            self.assertNotIn('mobile', row)
            self.assertNotIn('user', row)
        self.assertNotIn('09121112233', resp.content.decode())

    def test_a_human_technical_user_still_sees_the_same_fields(self):
        """The token adds no restriction of its own beyond read-only."""
        human = User.objects.create_user(username='tech-person', password='Zx9!kQ2mVr7t',
                                         role='technical')
        human_token = Token.objects.create(user=human)
        svc = self.client.get('/api/requests/', **self.auth).json()
        person = self.client.get(
            '/api/requests/', HTTP_AUTHORIZATION=f'Token {human_token.key}').json()
        svc_rows = svc['results'] if 'results' in svc else svc
        person_rows = person['results'] if 'results' in person else person
        self.assertEqual([sorted(r) for r in svc_rows], [sorted(r) for r in person_rows])

    def test_a_human_can_still_write(self):
        """Read-only applies to service accounts, not to staff."""
        boss = User.objects.create_user(username='boss-api', password='Zx9!kQ2mVr7t',
                                        role='admin', is_superuser=True, is_staff=True)
        boss_token = Token.objects.create(user=boss)
        resp = self.client.patch(
            f'/api/requests/{self.req.pk}/', {'city': 'کرج'},
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {boss_token.key}')
        self.assertNotEqual(resp.status_code, 403)

    def test_revoking_the_token_closes_the_door(self):
        Token.objects.filter(user=self.svc).delete()
        status = self.client.get('/api/requests/', **self.auth).status_code
        self.assertIn(status, (401, 403))
