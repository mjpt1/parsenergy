import logging

from . import traffic

logger = logging.getLogger(__name__)

STAFF_ROLES = ('admin', 'sales', 'technical', 'marketing', 'operations', 'financial')


class VisitTrackingMiddleware:
    """Count arrivals on public pages. Never lets tracking break a page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._track(request, response)
        except Exception:  # noqa: BLE001 - analytics is best effort
            logger.warning('visit tracking failed', exc_info=True)
        return response

    def _track(self, request, response):
        if request.method != 'GET' or response.status_code != 200:
            return
        if not response.get('Content-Type', '').startswith('text/html'):
            return
        if not traffic.is_tracked_path(request.path):
            return
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and (
                user.is_staff or user.is_superuser or getattr(user, 'role', '') in STAFF_ROLES):
            return
        ua = request.META.get('HTTP_USER_AGENT', '')
        if traffic.is_bot(ua):
            return
        visitor_id = request.COOKIES.get(traffic.VISITOR_COOKIE, '')
        is_new = not (len(visitor_id) == 32 and visitor_id.isalnum())
        if is_new:
            visitor_id = traffic.new_visitor_id()
            response.set_cookie(traffic.VISITOR_COOKIE, visitor_id,
                                max_age=traffic.VISITOR_COOKIE_AGE, samesite='Lax',
                                secure=request.is_secure(), httponly=True)
        traffic.record(
            visitor_id=visitor_id, is_new=is_new, host=request.get_host(),
            path=request.path, referrer=request.META.get('HTTP_REFERER', ''),
            query=request.GET, user_agent=ua)
