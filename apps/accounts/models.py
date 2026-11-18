from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.Model):
    name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255, blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Permission(models.Model):
    code = models.CharField(max_length=128, unique=True)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code


class RolePermission(models.Model):
    role = models.ForeignKey('Role', on_delete=models.CASCADE, related_name='role_permissions')
    permission = models.ForeignKey('Permission', on_delete=models.CASCADE, related_name='permission_roles')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('role', 'permission')

    def __str__(self):
        return f'{self.role} -> {self.permission}'


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = 'owner', 'مالک نیروگاه'
        ADMIN = 'admin', 'مدیریت'
        OPERATOR = 'operator', 'اپراتور'
        ANALYST = 'analyst', 'تحلیلگر'
        MARKETING = 'marketing', 'توسعه بازار'
        SALES = 'sales', 'فروش'
        TECHNICAL = 'technical', 'فنی'
        OPERATIONS = 'operations', 'عملیات'
        # Handles contracts, invoices and settlement. Reads the commercial end
        # of the pipeline; does not own a pipeline stage and cannot move one.
        FINANCIAL = 'financial', 'مالی'
        CUSTOMER = 'customer', 'مالک'
        # An outside company: sees only the projects it is connected to.
        CONTRACTOR = 'contractor', 'پیمانکار'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OWNER)
    roles = models.ManyToManyField('Role', through='UserRole', related_name='users', blank=True)
    # Optional, per-user extra access toggles managed by admins (beyond the main role).
    extra_permissions = models.ManyToManyField(
        'Permission', blank=True, related_name='granted_users')
    phone_number = models.CharField(max_length=20, blank=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=128, blank=True)
    last_mfa_at = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    timezone = models.CharField(max_length=64, default='Asia/Tehran')
    language = models.CharField(max_length=16, default='fa')

    def is_admin_role(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    def is_management(self):
        """Admins/superusers who oversee every department (NOT customers/owners)."""
        return self.is_superuser or self.role == self.Role.ADMIN

    def is_marketing(self):
        return self.role == self.Role.MARKETING

    def is_sales(self):
        return self.role == self.Role.SALES

    def is_technical(self):
        return self.role == self.Role.TECHNICAL

    def is_operations(self):
        return self.role == self.Role.OPERATIONS

    def is_financial(self):
        return self.role == self.Role.FINANCIAL

    def is_customer(self):
        return self.role == self.Role.CUSTOMER

    # --- Navigation capabilities (role default OR an admin-granted extra) ---
    @property
    def can_access_plants(self):
        return (self.is_superuser or self.role in (
            self.Role.ADMIN, self.Role.TECHNICAL, self.Role.OPERATIONS,
            self.Role.OWNER, self.Role.CUSTOMER,
        ) or self.has_permission_code('plants.access'))

    @property
    def can_manage_contractors(self):
        return self.is_superuser or self.role in (self.Role.ADMIN, self.Role.TECHNICAL, self.Role.OPERATIONS)

    @property
    def can_edit_plants(self):
        return self.is_superuser or self.role in (self.Role.ADMIN, self.Role.TECHNICAL, self.Role.OPERATIONS)

    @property
    def can_access_reports(self):
        return (self.is_superuser or self.role in (self.Role.ADMIN, self.Role.TECHNICAL)
                or self.has_permission_code('reports.access'))

    @property
    def can_build_proposal(self):
        # shortcut: trial run for one account only; switch to can_access_reports when it opens to staff.
        return self.username == 'mjpt1'

    @property
    def can_access_analytics(self):
        return (self.is_superuser or self.role in (self.Role.ADMIN, self.Role.TECHNICAL)
                or self.has_permission_code('analytics.access'))

    def has_permission_code(self, code: str) -> bool:
        if self.is_superuser or self.is_admin_role():
            return True
        if self.extra_permissions.filter(code=code).exists():
            return True
        return RolePermission.objects.filter(
            role__users=self,
            permission__code=code,
        ).exists()


class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='user_roles')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_roles')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'role')

    def __str__(self):
        return f'{self.user} -> {self.role}'
