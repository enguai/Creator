from django.conf import settings
from django.http import JsonResponse

from .form_automation import setting_or_env


PUBLIC_API_PATHS = {
    '/api/auth/session/',
    '/api/auth/login/',
    '/api/auth/logout/',
    '/api/auth/register/',
    '/api/auth/verification-code/',
    '/api/auth/recover-account/',
    '/api/auth/password-reset/',
    '/api/auth/password-reset-confirm/',
    '/api/forms/health/',
    '/api/payroll/health/',
    '/api/guard-license/activate/',
    '/api/guard-license/validate/',
}
WORKER_API_PREFIXES = (
    '/api/forms/worker/',
    '/api/payroll/worker/',
    '/api/knowledge/worker/',
)


def configured_worker_token():
    return setting_or_env('FORM_AUTOMATION_WORKER_TOKEN', '').strip()


def valid_worker_request(request):
    expected = configured_worker_token()
    supplied = request.headers.get('X-Creator-Worker-Token', '').strip()
    return bool(expected and supplied and supplied == expected)


class ApiLoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if not getattr(settings, 'AUTH_REQUIRE_LOGIN', True) or not path.startswith('/api/'):
            return self.get_response(request)
        if path in PUBLIC_API_PATHS:
            return self.get_response(request)
        if path.startswith(WORKER_API_PREFIXES) and valid_worker_request(request):
            return self.get_response(request)
        if path.startswith('/api/tasks/') and valid_worker_request(request):
            return self.get_response(request)
        if request.user.is_authenticated:
            return self.get_response(request)
        return JsonResponse(
            {'error': 'authentication_required', 'message': '请先登录后再使用网站功能。'},
            status=401,
            json_dumps_params={'ensure_ascii': False},
        )


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/admin/'):
            response['X-Frame-Options'] = 'SAMEORIGIN'
        elif 'X-Frame-Options' not in response:
            response['X-Frame-Options'] = 'DENY'
        if 'Referrer-Policy' not in response:
            response['Referrer-Policy'] = 'same-origin'
        if 'X-Content-Type-Options' not in response:
            response['X-Content-Type-Options'] = 'nosniff'
        return response
