from django.conf import settings
from django.db import models
from decimal import Decimal


class VPP(models.Model):
    name = models.CharField(max_length=255)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vpps')
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class VPPMember(models.Model):
    vpp = models.ForeignKey(VPP, on_delete=models.CASCADE, related_name='members')
    plant = models.ForeignKey('plants.Plant', on_delete=models.CASCADE, related_name='vpp_memberships')
    contribution_kw = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('vpp', 'plant')

    def __str__(self):
        return f"{self.vpp.name} - {self.plant.name}"


class DispatchSchedule(models.Model):
    vpp = models.ForeignKey(VPP, on_delete=models.CASCADE, related_name='schedules')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    target_power_kw = models.DecimalField(max_digits=12, decimal_places=2)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vpp.name} [{self.start_time} - {self.end_time}] -> {self.target_power_kw} kW"
