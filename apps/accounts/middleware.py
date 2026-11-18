import re

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from apps.core.services import write_audit_log

# Everything a contractor account can reach; the rest of the site is staff or customer ground.
CONTRACTOR_PATHS = re.compile(
    r'^/(requests/contractor/|requests/project/documents/\d+/file/$|accounts/(logout|profile)/|static/|favicon)')


class RoleRoutingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.current_role = getattr(request.user, 'role', 'owner')
            if request.current_role == 'contractor' and not CONTRACTOR_PATHS.match(request.path):
                if request.method not in ('GET', 'HEAD'):
                    raise PermissionDenied
                return redirect(reverse('requests:contractor-home'))
        response = self.get_response(request)

        if request.user.is_authenticated and request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            write_audit_log(
                actor=request.user,
                action=f'http.{request.method.lower()}',
                target_type='endpoint',
                target_id=request.path,
                metadata={'status_code': response.status_code},
                ip_address=request.META.get('REMOTE_ADDR'),
            )
        return response
