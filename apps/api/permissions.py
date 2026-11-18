"""Access rules for integration accounts.

The Vida assistant connects as an ordinary user, so every queryset scope and
every field-level redaction the panel already applies applies to it too — a
technical-role token sees exactly what a technical member of staff sees, no
more and no less. What it must *not* have is the ability to change anything,
and that cannot rest on the integration choosing not to send a POST.

`ReadOnlyForIntegrations` enforces it on the server: an account flagged as an
integration may only use the safe HTTP methods. The flag lives on the user, so
revoking access is deleting one token row — no redeploy, no config change.
"""
from rest_framework import permissions

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

#: Marks a user as a machine integration rather than a person. Kept as a
#: `SystemParameter`-free convention so no migration is needed: any username in
#: this group is read-only. See `INTEGRATION_USERNAME_PREFIX`.
INTEGRATION_USERNAME_PREFIX = 'svc-'


def is_integration(user) -> bool:
    """A service account is one whose username is namespaced as such.

    Deliberately a naming convention rather than a new column: it is visible at
    a glance in the user list, survives every future migration, and cannot be
    switched off by editing a record that someone mistook for a profile field.
    """
    username = getattr(user, 'username', '') or ''
    return username.startswith(INTEGRATION_USERNAME_PREFIX)


class ReadOnlyForIntegrations(permissions.BasePermission):
    """Humans keep their normal rights; service accounts may only read."""

    message = 'This integration token is read-only.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if is_integration(request.user):
            return request.method in SAFE_METHODS
        return True

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
