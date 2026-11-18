from django.conf import settings
from django.db import models
from decimal import Decimal


class VPP(models.Model):
    name = models.CharField(max_length=255, verbose_name='نام')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vpps', verbose_name='مالک')
    description = models.TextField(blank=True, verbose_name='توضیحات')
    active = models.BooleanField(default=True, verbose_name='فعال')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class VPPMember(models.Model):
    vpp = models.ForeignKey(VPP, on_delete=models.CASCADE, related_name='members', verbose_name='نیروگاه مجازی')
    plant = models.ForeignKey('plants.Plant', on_delete=models.CASCADE, related_name='vpp_memberships', verbose_name='نیروگاه')
    contribution_kw = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'), verbose_name='سهم (کیلووات)')
    is_active = models.BooleanField(default=True, verbose_name='فعال')

    class Meta:
        unique_together = ('vpp', 'plant')

    def __str__(self):
        return f"{self.vpp.name} - {self.plant.name}"


class DispatchSchedule(models.Model):
    vpp = models.ForeignKey(VPP, on_delete=models.CASCADE, related_name='schedules', verbose_name='نیروگاه مجازی')
    start_time = models.DateTimeField(verbose_name='زمان شروع')
    end_time = models.DateTimeField(verbose_name='زمان پایان')
    target_power_kw = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='توان هدف (کیلووات)')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vpp.name} [{self.start_time} - {self.end_time}] -> {self.target_power_kw} kW"
