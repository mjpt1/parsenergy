from django import forms
from .models import VPP, VPPMember, DispatchSchedule


class VPPForm(forms.ModelForm):
    class Meta:
        model = VPP
        fields = ['name', 'description', 'active']


class VPPMemberForm(forms.ModelForm):
    class Meta:
        model = VPPMember
        fields = ['vpp', 'plant', 'contribution_kw', 'is_active']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            vpp_field = self.fields['vpp']
            plant_field = self.fields['plant']
            vpp_field.queryset = vpp_field.queryset.filter(owner=user)
            plant_field.queryset = plant_field.queryset.filter(owner=user)


class DispatchScheduleForm(forms.ModelForm):
    class Meta:
        model = DispatchSchedule
        fields = ['vpp', 'start_time', 'end_time', 'target_power_kw']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user is not None and not (user.is_superuser or getattr(user, 'role', '') == 'admin'):
            vpp_field = self.fields['vpp']
            vpp_field.queryset = vpp_field.queryset.filter(owner=user)
