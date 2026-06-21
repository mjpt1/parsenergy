from rest_framework import serializers

from .models import (
    Request,
    RequestOffer,
    RequestContract,
    RequestPayment,
    RequestMessageLog,
    OtpVerification,
)

# OTP purposes that may be requested through the public endpoint.
PUBLIC_OTP_PURPOSES = [
    (OtpVerification.Purpose.REGISTER, OtpVerification.Purpose.REGISTER.label),
    (OtpVerification.Purpose.LOGIN, OtpVerification.Purpose.LOGIN.label),
]


class RequestOfferSerializer(serializers.ModelSerializer):
    is_payable = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = RequestOffer
        fields = [
            'id', 'request', 'title', 'amount', 'currency', 'description',
            'valid_until', 'is_active', 'is_payable', 'is_expired',
            'created_by', 'created_at',
        ]
        read_only_fields = ['request', 'created_by', 'created_at']


class RequestContractSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = RequestContract
        fields = [
            'id', 'request', 'offer', 'contract_number', 'body',
            'status', 'status_display', 'approved_at', 'created_at',
        ]
        read_only_fields = fields


class RequestPaymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = RequestPayment
        fields = [
            'id', 'request', 'offer', 'amount', 'token',
            'status', 'status_display', 'gateway_ref', 'paid_at', 'created_at',
        ]
        read_only_fields = fields


class RequestMessageLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequestMessageLog
        fields = [
            'id', 'request', 'user', 'mobile', 'message_type', 'body',
            'provider', 'provider_message_id', 'status', 'created_at',
        ]
        read_only_fields = fields


class RequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Request
        fields = [
            'id', 'user', 'full_name', 'mobile', 'province', 'city',
            'description', 'status', 'status_display', 'created_at', 'updated_at',
        ]
        read_only_fields = ['user', 'status', 'status_display', 'created_at', 'updated_at']


# --- input serializers (actions) ---

class OfferCreateSerializer(serializers.Serializer):
    request = serializers.IntegerField()
    title = serializers.CharField(max_length=255)
    amount = serializers.DecimalField(max_digits=14, decimal_places=0)
    currency = serializers.CharField(max_length=8, required=False, default='IRR')
    description = serializers.CharField(required=False, allow_blank=True, default='')
    valid_until = serializers.DateTimeField(required=False, allow_null=True)


class SelectOfferSerializer(serializers.Serializer):
    offer_id = serializers.IntegerField()


class ApproveContractSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=8)


class OtpRequestSerializer(serializers.Serializer):
    mobile = serializers.CharField(max_length=20)
    purpose = serializers.ChoiceField(choices=PUBLIC_OTP_PURPOSES)


class OtpVerifySerializer(serializers.Serializer):
    mobile = serializers.CharField(max_length=20)
    code = serializers.CharField(max_length=8)
    purpose = serializers.ChoiceField(choices=PUBLIC_OTP_PURPOSES)
