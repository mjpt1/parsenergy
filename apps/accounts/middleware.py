from apps.core.services import write_audit_log


class RoleRoutingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request.current_role = getattr(request.user, 'role', 'owner')
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
