from django.contrib import admin

from .models import Lead, LeadSource


@admin.register(LeadSource)
class LeadSourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'marketer', 'event_name', 'is_active', 'token', 'created_at')
    list_filter = ('is_active', 'event_name')
    search_fields = ('name', 'event_name', 'marketer__username')
    readonly_fields = ('token', 'created_at')


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    """Exhibition extras. The lead itself is managed as a request."""

    list_display = ('lead_code', 'visitor', 'company', 'temperature',
                    'stage2_completed', 'marketer', 'created_at')
    list_filter = ('temperature', 'stage2_completed', 'event_name', 'marketer')
    search_fields = ('lead_code', 'company', 'request__full_name', 'request__mobile')
    readonly_fields = ('lead_code', 'resume_token', 'created_at', 'updated_at')
    raw_id_fields = ('request',)

    @admin.display(description='مشتری')
    def visitor(self, obj):
        return obj.request.full_name if obj.request_id else '—'
