from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PublicRegistrationTests(TestCase):
    def test_public_registration_cannot_choose_admin_role(self):
        response = self.client.post(
            reverse('accounts:register'),
            {
                'username': 'customer1',
                'email': 'customer@example.com',
                'phone_number': '09120000000',
                'role': 'admin',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            },
            HTTP_HOST='localhost',
        )

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='customer1')
        self.assertEqual(user.role, get_user_model().Role.OWNER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
