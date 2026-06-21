from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from . import repositories
from .models import (
    OtpVerification,
    Request,
    RequestContract,
    RequestMessageLog,
    RequestOffer,
    RequestPayment,
)
from .serializers import (
    ApproveContractSerializer,
    OfferCreateSerializer,
    OtpRequestSerializer,
    OtpVerifySerializer,
    RequestContractSerializer,
    RequestMessageLogSerializer,
    RequestOfferSerializer,
    RequestPaymentSerializer,
    RequestSerializer,
    SelectOfferSerializer,
)
from .services import contracts as contract_service
from .services import lifecycle
from .services import offers as offer_service
from .services import otp as otp_service

User = get_user_model()


class IsRequestManager(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and repositories.is_request_manager(request.user)
        )


class RequestViewSet(viewsets.ModelViewSet):
    serializer_class = RequestSerializer

    def get_queryset(self):
        return repositories.requests_for_user(self.request.user)

    def get_permissions(self):
        if self.action == 'destroy':
            return [permissions.IsAuthenticated(), IsRequestManager()]
        return [permissions.IsAuthenticated()]

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = lifecycle.create_request(
            full_name=data['full_name'],
            mobile=data['mobile'],
            province=data['province'],
            city=data.get('city', ''),
            description=data.get('description', ''),
            user=self.request.user,
        )

    @action(detail=True, methods=['get'])
    def offers(self, request, pk=None):
        obj = self.get_object()
        return Response(RequestOfferSerializer(obj.offers.all(), many=True).data)

    @action(detail=True, methods=['post'], url_path='select-offer')
    def select_offer(self, request, pk=None):
        obj = self.get_object()
        payload = SelectOfferSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        offer = get_object_or_404(RequestOffer, pk=payload.validated_data['offer_id'], request=obj)
        try:
            contract = offer_service.select_offer(request=obj, offer=offer, actor=request.user)
        except offer_service.OfferError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RequestContractSerializer(contract).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def contract(self, request, pk=None):
        obj = self.get_object()
        contract = RequestContract.objects.filter(request=obj).first()
        if contract is None:
            return Response({'detail': 'قراردادی موجود نیست.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(RequestContractSerializer(contract).data)

    @action(detail=True, methods=['post'], url_path='contract/request-otp')
    def request_contract_otp(self, request, pk=None):
        obj = self.get_object()
        contract = RequestContract.objects.filter(request=obj).first()
        if contract is None:
            return Response({'detail': 'قراردادی موجود نیست.'}, status=status.HTTP_404_NOT_FOUND)
        contract_service.request_approval_otp(contract)
        return Response({'detail': 'کد تأیید قرارداد ارسال شد.'})

    @action(detail=True, methods=['post'], url_path='contract/approve')
    def approve_contract(self, request, pk=None):
        obj = self.get_object()
        contract = RequestContract.objects.filter(request=obj).first()
        if contract is None:
            return Response({'detail': 'قراردادی موجود نیست.'}, status=status.HTTP_404_NOT_FOUND)
        payload = ApproveContractSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            contract_service.approve_with_otp(
                contract=contract, code=payload.validated_data['code'], actor=request.user,
            )
        except (otp_service.OtpError, contract_service.ContractError) as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RequestContractSerializer(contract).data)

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        obj = self.get_object()
        return Response(RequestMessageLogSerializer(obj.message_logs.all(), many=True).data)


class RequestOfferViewSet(viewsets.ModelViewSet):
    serializer_class = RequestOfferSerializer

    def get_queryset(self):
        return RequestOffer.objects.filter(
            request__in=repositories.requests_for_user(self.request.user)
        ).select_related('request')

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy', 'toggle'):
            return [permissions.IsAuthenticated(), IsRequestManager()]
        return [permissions.IsAuthenticated()]

    def create(self, request, *args, **kwargs):
        payload = OfferCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        target = get_object_or_404(Request, pk=data['request'])
        try:
            offer = offer_service.add_offer(
                request=target,
                title=data['title'],
                amount=data['amount'],
                currency=data.get('currency', 'IRR'),
                description=data.get('description', ''),
                valid_until=data.get('valid_until'),
                created_by=request.user,
            )
        except offer_service.OfferError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RequestOfferSerializer(offer).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def toggle(self, request, pk=None):
        offer = self.get_object()
        offer_service.toggle_active(offer, actor=request.user)
        return Response(RequestOfferSerializer(offer).data)


class RequestContractViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RequestContractSerializer

    def get_queryset(self):
        return RequestContract.objects.filter(
            request__in=repositories.requests_for_user(self.request.user)
        ).select_related('request', 'offer')


class RequestPaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RequestPaymentSerializer

    def get_queryset(self):
        return RequestPayment.objects.filter(
            request__in=repositories.requests_for_user(self.request.user)
        ).select_related('request', 'offer')


class RequestMessageLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = RequestMessageLogSerializer
    permission_classes = [permissions.IsAuthenticated, IsRequestManager]
    queryset = RequestMessageLog.objects.all().order_by('-created_at')


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def otp_request(request):
    """Issue an OTP for registration or login (rule 7: no duplicate mobile)."""
    payload = OtpRequestSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    mobile = payload.validated_data['mobile']
    purpose = payload.validated_data['purpose']

    exists = User.objects.filter(username=mobile).exists()
    if purpose == OtpVerification.Purpose.REGISTER and exists:
        return Response({'detail': 'این شماره قبلاً ثبت‌نام شده است.'}, status=status.HTTP_400_BAD_REQUEST)
    if purpose == OtpVerification.Purpose.LOGIN and not exists:
        return Response({'detail': 'کاربری با این شماره یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

    otp_service.issue(mobile=mobile, purpose=purpose)
    return Response({'detail': 'کد یک‌بارمصرف ارسال شد.'})


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def otp_verify(request):
    """Verify an OTP, create/find the user, and return an auth token."""
    payload = OtpVerifySerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    mobile = payload.validated_data['mobile']
    code = payload.validated_data['code']
    purpose = payload.validated_data['purpose']

    try:
        otp_service.verify(mobile=mobile, code=code, purpose=purpose)
    except otp_service.OtpError as exc:
        return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.filter(username=mobile).first()
    created = False
    if user is None:
        user = User(username=mobile, phone_number=mobile)
        user.set_unusable_password()
        user.save()
        created = True

    # Attach any requests submitted anonymously with this mobile.
    Request.objects.filter(mobile=mobile, user__isnull=True).update(user=user)

    token, _ = Token.objects.get_or_create(user=user)
    return Response({'detail': 'ورود موفق.', 'token': token.key, 'created': created})
