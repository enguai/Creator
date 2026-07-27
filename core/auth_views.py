import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Profile, UserSecurityEvent


LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_MINUTES = 15


def response_json(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


def request_payload(request):
    try:
        return json.loads(request.body.decode('utf-8')) if request.body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def client_ip(request):
    forwarded = request.headers.get('X-Forwarded-For', '')
    return (forwarded.split(',', 1)[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None


def record_event(request, event, user=None, username='', details=None):
    UserSecurityEvent.objects.create(
        user=user,
        username=username or (user.username if user else ''),
        event=event,
        ip_address=client_ip(request),
        details=details or {},
    )


def serialize_user(user):
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'is_staff': user.is_staff,
        'display_name': user.get_full_name() or user.username,
    }


def form_errors(form):
    return {
        field: [item['message'] for item in errors]
        for field, errors in form.errors.get_json_data().items()
    }


def is_login_blocked(request, username):
    since = timezone.now() - timedelta(minutes=LOGIN_FAILURE_WINDOW_MINUTES)
    events = UserSecurityEvent.objects.filter(
        username__iexact=username,
        ip_address=client_ip(request),
        created_at__gte=since,
    )
    last_success = events.filter(event=UserSecurityEvent.Event.LOGIN_SUCCEEDED).order_by('-created_at').first()
    if last_success:
        events = events.filter(created_at__gt=last_success.created_at)
    return events.filter(event=UserSecurityEvent.Event.LOGIN_FAILED).count() >= LOGIN_FAILURE_LIMIT


@ensure_csrf_cookie
@require_GET
def session_detail(request):
    return response_json({
        'authenticated': request.user.is_authenticated,
        'user': serialize_user(request.user) if request.user.is_authenticated else None,
    })


@require_POST
def login_user(request):
    payload = request_payload(request)
    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', ''))

    if not username or not password:
        return response_json({'message': '请输入账号和密码。'}, status=400)
    if is_login_blocked(request, username):
        record_event(request, UserSecurityEvent.Event.LOGIN_BLOCKED, username=username)
        return response_json({'message': '登录失败次数过多，请 15 分钟后再试。'}, status=429)

    user = authenticate(request, username=username, password=password)
    if user is None:
        record_event(request, UserSecurityEvent.Event.LOGIN_FAILED, username=username)
        return response_json({'message': '账号或密码不正确。'}, status=401)
    if not user.is_active:
        record_event(request, UserSecurityEvent.Event.LOGIN_FAILED, user=user)
        return response_json({'message': '该账号已被停用，请联系管理员。'}, status=403)

    login(request, user)
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if payload.get('remember_me') else 0)
    record_event(request, UserSecurityEvent.Event.LOGIN_SUCCEEDED, user=user)
    return response_json({'authenticated': True, 'user': serialize_user(user)})


@require_POST
def logout_user(request):
    user = request.user if request.user.is_authenticated else None
    if user:
        record_event(request, UserSecurityEvent.Event.LOGGED_OUT, user=user)
    logout(request)
    return response_json({'authenticated': False, 'user': None})


@require_POST
def register_user(request):
    payload = request_payload(request)
    email = str(payload.get('email', '')).strip().lower()
    form = UserCreationForm({
        'username': str(payload.get('username', '')).strip(),
        'password1': str(payload.get('password1', '')),
        'password2': str(payload.get('password2', '')),
    })

    errors = form_errors(form) if not form.is_valid() else {}
    if not email:
        errors['email'] = ['请输入用于找回账号和密码的邮箱。']
    elif User.objects.filter(email__iexact=email).exists():
        errors['email'] = ['该邮箱已经注册，请直接登录或找回账号。']
    if errors:
        return response_json({'message': '请检查注册信息。', 'field_errors': errors}, status=400)

    with transaction.atomic():
        user = form.save(commit=False)
        user.email = email
        user.save()
        Profile.objects.get_or_create(user=user, defaults={'nickname': user.username})
        record_event(request, UserSecurityEvent.Event.REGISTERED, user=user)

    login(request, user)
    request.session.set_expiry(0)
    record_event(request, UserSecurityEvent.Event.LOGIN_SUCCEEDED, user=user, details={'source': 'registration'})
    return response_json({'authenticated': True, 'user': serialize_user(user)}, status=201)


@require_POST
def recover_account(request):
    email = str(request_payload(request).get('email', '')).strip().lower()
    if not email:
        return response_json({'message': '请输入注册邮箱。'}, status=400)

    users = list(User.objects.filter(email__iexact=email, is_active=True).order_by('date_joined')[:5])
    if users:
        account_names = '、'.join(user.username for user in users)
        try:
            send_mail(
                '造物者账号找回',
                f'该邮箱对应的造物者账号：{account_names}\n\n如果不是你本人操作，请忽略此邮件。',
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as exc:
            record_event(
                request,
                UserSecurityEvent.Event.ACCOUNT_RECOVERY,
                username=users[0].username,
                details={'email_sent': False, 'error': str(exc)[:300]},
            )
        else:
            record_event(
                request,
                UserSecurityEvent.Event.ACCOUNT_RECOVERY,
                username=users[0].username,
                details={'email_sent': True},
            )
    return response_json({'message': '如果该邮箱已注册，账号信息会发送到邮箱。'})


@require_POST
def request_password_reset(request):
    email = str(request_payload(request).get('email', '')).strip().lower()
    if not email:
        return response_json({'message': '请输入注册邮箱。'}, status=400)

    users = list(User.objects.filter(email__iexact=email, is_active=True).order_by('date_joined')[:5])
    for user in users:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        base_url = settings.FRONTEND_BASE_URL.rstrip('/') or request.build_absolute_uri('/').rstrip('/')
        reset_url = f'{base_url}/reset-password/{uid}/{token}'
        try:
            send_mail(
                '重置造物者账号密码',
                f'请打开下面的链接重置密码，链接仅在限定时间内有效：\n{reset_url}\n\n如果不是你本人操作，请忽略此邮件。',
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False,
            )
        except Exception as exc:
            record_event(
                request,
                UserSecurityEvent.Event.PASSWORD_RESET_REQUESTED,
                user=user,
                details={'email_sent': False, 'error': str(exc)[:300]},
            )
        else:
            record_event(
                request,
                UserSecurityEvent.Event.PASSWORD_RESET_REQUESTED,
                user=user,
                details={'email_sent': True},
            )
    return response_json({'message': '如果该邮箱已注册，密码重置链接会发送到邮箱。'})


@require_POST
def confirm_password_reset(request):
    payload = request_payload(request)
    try:
        user_id = force_str(urlsafe_base64_decode(str(payload.get('uid', ''))))
        user = User.objects.get(pk=user_id, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return response_json({'message': '密码重置链接无效或已经过期。'}, status=400)

    token = str(payload.get('token', ''))
    if not default_token_generator.check_token(user, token):
        return response_json({'message': '密码重置链接无效或已经过期。'}, status=400)

    form = SetPasswordForm(user, {
        'new_password1': str(payload.get('password1', '')),
        'new_password2': str(payload.get('password2', '')),
    })
    if not form.is_valid():
        return response_json(
            {'message': '请检查新密码。', 'field_errors': form_errors(form)},
            status=400,
        )

    form.save()
    record_event(request, UserSecurityEvent.Event.PASSWORD_RESET_COMPLETED, user=user)
    return response_json({'message': '密码已重置，请使用新密码登录。'})


def csrf_failure(request, reason=''):
    return response_json({'message': '页面安全校验已过期，请刷新页面后重试。'}, status=403)
