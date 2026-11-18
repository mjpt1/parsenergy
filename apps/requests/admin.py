from django.contrib import admin
from django.forms.models import BaseInlineFormSet

from .models import (
    Request,
    RequestOffer,
    RequestContract,
    RequestPayment,
    OtpVerification,
    RequestMessageLog,
    UserProfileCompletion,
    ContractTemplate,
    ContractSettings,
    RequestFormStep,
    RequestFormField,
    Ticket,
    TicketMessage,
)


@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'full_name', 'mobile', 'province', 'status', 'created_at')
    list_filter = ('status', 'province')
    search_fields = ('full_name', 'mobile')


@admin.register(RequestOffer)
class RequestOfferAdmin(admin.ModelAdmin):
    list_display = ('id', 'request', 'title', 'amount', 'currency', 'is_active', 'valid_until')
    list_filter = ('is_active', 'currency')


@admin.register(RequestContract)
class RequestContractAdmin(admin.ModelAdmin):
    list_display = ('contract_number', 'request', 'offer', 'status', 'approved_at')
    list_filter = ('status',)


@admin.register(RequestPayment)
class RequestPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'request', 'offer', 'amount', 'status', 'paid_at')
    list_filter = ('status',)


@admin.register(OtpVerification)
class OtpVerificationAdmin(admin.ModelAdmin):
    list_display = ('mobile', 'purpose', 'is_used', 'expires_at', 'created_at')
    list_filter = ('purpose', 'is_used')


@admin.register(RequestMessageLog)
class RequestMessageLogAdmin(admin.ModelAdmin):
    list_display = ('mobile', 'message_type', 'status', 'provider', 'created_at')
    list_filter = ('message_type', 'status')


@admin.register(UserProfileCompletion)
class UserProfileCompletionAdmin(admin.ModelAdmin):
    list_display = ('user', 'national_id', 'is_completed', 'completed_at')
    list_filter = ('is_completed',)


@admin.register(ContractTemplate)
class ContractTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'updated_at')
    list_filter = ('is_active',)


@admin.register(ContractSettings)
class ContractSettingsAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'updated_at')


class _RequestFormFieldFormSet(BaseInlineFormSet):
    """Disables the per-row delete checkbox for system fields so a step's
    inline formset can't silently drop a field business logic depends on."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if form.instance.pk and form.instance.is_system and 'DELETE' in form.fields:
            form.fields['DELETE'].disabled = True


class RequestFormFieldInline(admin.TabularInline):
    """Fields belonging to one step of the evaluation-form builder.

    System fields (is_system=True) power business-critical logic elsewhere
    (Shahkar identity check, OTP, pipeline fields) and must not be deleted or
    retyped from here — only their label/help text/order/step may change.
    Fields the admin adds themselves (is_system=False) are fully editable.
    """
    model = RequestFormField
    formset = _RequestFormFieldFormSet
    extra = 0
    fields = ('order', 'key', 'field_type', 'label', 'help_text', 'required',
               'choices', 'condition', 'is_system', 'is_active')

    def get_readonly_fields(self, request, obj=None):
        # `key`/`field_type`/`is_system` are always locked once created: changing
        # a system field's key would silently disconnect it from the real form
        # field/model column it's supposed to represent.
        return ('key', 'field_type', 'is_system')


@admin.register(RequestFormStep)
class RequestFormStepAdmin(admin.ModelAdmin):
    list_display = ('order', 'label', 'is_active', 'field_count')
    list_editable = ('is_active',)
    ordering = ('order',)
    inlines = [RequestFormFieldInline]

    def field_count(self, obj):
        return obj.fields.count()
    field_count.short_description = 'تعداد فیلد'


@admin.register(RequestFormField)
class RequestFormFieldAdmin(admin.ModelAdmin):
    list_display = ('label', 'key', 'step', 'field_type', 'order', 'is_system', 'is_active')
    list_filter = ('step', 'field_type', 'is_system', 'is_active')
    search_fields = ('key', 'label')

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_system:
            return ('key', 'field_type', 'is_system')
        return ('is_system',) if obj else ()

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_system:
            return False
        return super().has_delete_permission(request, obj)


class TicketMessageInline(admin.TabularInline):
    model = TicketMessage
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'subject', 'user', 'status', 'priority', 'updated_at')
    list_filter = ('status', 'priority')
    search_fields = ('subject',)
    inlines = [TicketMessageInline]


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'ticket', 'author', 'is_staff_reply', 'created_at')
    list_filter = ('is_staff_reply',)
