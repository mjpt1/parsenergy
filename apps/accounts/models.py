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
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Admin'
        OPERATOR = 'operator', 'Operator'
        ANALYST = 'analyst', 'Analyst'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OWNER)
    roles = models.ManyToManyField('Role', through='UserRole', related_name='users', blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=128, blank=True)
    last_mfa_at = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    timezone = models.CharField(max_length=64, default='Asia/Tehran')
    language = models.CharField(max_length=16, default='fa')

    def is_admin_role(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    def has_permission_code(self, code: str) -> bool:
        if self.is_superuser or self.is_admin_role():
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
