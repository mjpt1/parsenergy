"""One-off helper: create the initial staff accounts for the Pars Energy panel.

Idempotent — an existing username is skipped (never silently re-passworded), so
running it twice is safe. Each account is a plain panel user: no `is_staff`,
no `is_superuser`, so none of them can reach Django admin. Access is driven
purely by `role`, matching what the panel's sidebar checks.

    python manage.py seed_staff
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()

STAFF = [
    ('admin2',     'jd934ne8d4k5', 'admin',      'مدیر سامانه'),
    ('sales1',     '1w9zd3sum67z', 'sales',      'کارشناس فروش'),
    ('tech1',      'vlzwbsv35ctl', 'technical',  'کارشناس فنی'),
    ('marketing1', '1upt1us53m5f', 'marketing',  'کارشناس توسعه بازار'),
    ('ops1',       's4hgcc9ryyin', 'operations', 'کارشناس عملیات'),
]


class Command(BaseCommand):
    help = 'Create the initial sales/technical/marketing/operations/admin panel users.'

    def handle(self, *args, **options):
        for username, password, role, full_name in STAFF:
            if User.objects.filter(username=username).exists():
                self.stdout.write(self.style.WARNING(f'skip   {username} (already exists)'))
                continue
            User.objects.create_user(
                username=username,
                password=password,
                first_name=full_name,
                role=role,
                is_staff=False,
                is_superuser=False,
            )
            self.stdout.write(self.style.SUCCESS(f'create {username:<12} role={role}'))
        self.stdout.write('')
        self.stdout.write('Panel users now:')
        for u in User.objects.order_by('id'):
            flag = ' (superuser)' if u.is_superuser else ''
            self.stdout.write(f'  {u.username:<12} {u.role}{flag}')
