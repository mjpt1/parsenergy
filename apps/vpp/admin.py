from django.contrib import admin
from .models import VPP, VPPMember, DispatchSchedule


admin.site.register(VPP)
admin.site.register(VPPMember)
admin.site.register(DispatchSchedule)
