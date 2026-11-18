class NoStoreHTMLMiddleware:
    """Stop browsers/proxies from caching dynamic HTML pages.

    A cached HTML page keeps a stale CSRF token that no longer matches the
    visitor's current ``csrftoken`` cookie, which Django rejects on submit as
    "CSRF token from POST incorrect" (403). Static assets are untouched, so
    WhiteNoise's long-term caching of CSS/JS still applies.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        ctype = response.get('Content-Type', '')
        if ctype.startswith('text/html') and not response.has_header('Cache-Control'):
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response['Pragma'] = 'no-cache'
        return response
