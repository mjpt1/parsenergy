from django.urls import path
from rest_framework.routers import DefaultRouter

from .api_views import (
    RequestViewSet,
    RequestOfferViewSet,
    RequestContractViewSet,
    RequestPaymentViewSet,
    RequestMessageLogViewSet,
    otp_request,
    otp_verify,
)

router = DefaultRouter()
router.register('requests', RequestViewSet, basename='svc-request')
router.register('request-offers', RequestOfferViewSet, basename='request-offer')
router.register('request-contracts', RequestContractViewSet, basename='request-contract')
router.register('request-payments', RequestPaymentViewSet, basename='request-payment')
router.register('request-message-logs', RequestMessageLogViewSet, basename='request-message-log')

urlpatterns = [
    path('request-otp/request/', otp_request, name='request-otp-request'),
    path('request-otp/verify/', otp_verify, name='request-otp-verify'),
] + router.urls
