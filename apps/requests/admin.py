from django.contrib import admin

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
