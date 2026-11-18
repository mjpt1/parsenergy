"""Issue (or re-issue) a read-only API token for an outside integration.

    python manage.py create_integration_token --name vida --role technical

The account is named `svc-<name>`, which is what makes it read-only — see
`apps.api.permissions`. Re-running the command rotates the token: the old one
stops working immediately, which is also how access is revoked.

    python manage.py create_integration_token --name vida --revoke
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

from apps.api.permissions import INTEGRATION_USERNAME_PREFIX

User = get_user_model()


class Command(BaseCommand):
    help = 'Create, rotate or revoke a read-only integration token.'

    def add_arguments(self, parser):
        parser.add_argument('--name', required=True,
                            help='Short integration name, e.g. "vida".')
        parser.add_argument('--role', default='technical',
                            help='Role whose visibility the token inherits (default: technical).')
        parser.add_argument('--revoke', action='store_true',
                            help='Delete the token and deactivate the account.')

    def handle(self, *args, **options):
        name = options['name'].strip().lower()
        if not name:
            raise CommandError('--name must not be empty')
        username = f'{INTEGRATION_USERNAME_PREFIX}{name}'

        if options['revoke']:
            user = User.objects.filter(username=username).first()
            if not user:
                raise CommandError(f'No integration account "{username}".')
            Token.objects.filter(user=user).delete()
            user.is_active = False
            user.save(update_fields=['is_active'])
            self.stdout.write(self.style.SUCCESS(f'Revoked: {username} (account disabled).'))
            return

        role = options['role'].strip()
        valid_roles = dict(User.Role.choices)
        if role not in valid_roles:
            raise CommandError(f'Unknown role "{role}". Valid: {", ".join(valid_roles)}')

        user, created = User.objects.get_or_create(
            username=username, defaults={'role': role})
        user.role = role
        user.is_active = True
        # A service account is not a person: no admin, no panel privileges, and
        # an unusable password so it can only ever arrive by token.
        user.is_staff = False
        user.is_superuser = False
        user.set_unusable_password()
        user.save()

        Token.objects.filter(user=user).delete()  # rotate
        token = Token.objects.create(user=user)

        self.stdout.write(self.style.SUCCESS(
            f'{"Created" if created else "Rotated"} {username} (role={role}, read-only)'))
        self.stdout.write(f'TOKEN {token.key}')
