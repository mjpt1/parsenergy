from django.contrib import admin
from .models import AlertRule, AlertEvent, Notification

admin.site.register(AlertRule)
admin.site.register(AlertEvent)
admin.site.register(Notification)
