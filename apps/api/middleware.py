"""Hard read-only boundary for integration accounts.

A DRF permission class is not enough. `DEFAULT_PERMISSION_CLASSES` is only a
default: any viewset that sets `permission_classes` or overrides
`get_permissions()` silently replaces it, and several already do — which is how
a read-only token was still able to POST a new request. The guarantee the
customer is being given ("no write operation is possible through this
connection") cannot depend on every present and future viewset remembering.

So it lives in middleware, outside the view layer, where nothing can override
it: if the authenticated user is a service account and the method is not safe,
the request never reaches a view.
"""
from django.http import JsonResponse
from rest_framework.authtoken.models import Token

from .permissions import SAFE_METHODS, is_integration


class IntegrationReadOnlyMiddleware:
    """Refuse every unsafe method from a service account."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in SAFE_METHODS and self._is_integration_request(request):
            return JsonResponse(
                {'detail': 'این توکن فقط‌خواندنی است و اجازهٔ تغییر اطلاعات ندارد.'},
                status=403)
        return self.get_response(request)

    @staticmethod
    def _is_integration_request(request):
        """Identify the caller before authentication has run.

        Middleware sits ahead of DRF, so `request.user` is not resolved yet for
        a token-authenticated call. The token is read straight off the header;
        a session user is checked the ordinary way.
        """
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if header.startswith('Token '):
            key = header.split(' ', 1)[1].strip()
            token = Token.objects.filter(key=key).select_related('user').first()
            return bool(token and is_integration(token.user))

        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated and is_integration(user))
