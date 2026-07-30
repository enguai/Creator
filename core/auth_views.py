import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Profile, UserSecurityEvent, VerificationCode
from .verification import deliver_code


LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_MINUTES = 15
VERIFICATION_PURPOSE_CHANNELS = {
    VerificationCode.Purpose.ACCOUNT_RECOVERY: VerificationCode.Channel.EMAIL,
    VerificationCode.Purpose.PASSWORD_RESET: VerificationCode.Channel.EMAIL,
}


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


def normalize_destination(channel, value):
    destination = str(value or '').strip().lower()
    validate_email(destination)
    return destination


def eligible_users(channel, purpose, destination):
    return User.objects.filter(email__iexact=destination, is_active=True)


def verification_sent_message(channel):
    return '如果信息匹配，验证码会发送到你的邮箱。'


def create_verification_code(request, channel, purpose, destination_value):
    if VERIFICATION_PURPOSE_CHANNELS.get(purpose) != channel:
        return response_json({'message': '验证码用途不正确。'}, status=400)

    try:
        destination = normalize_destination(channel, destination_value)
    except ValidationError as exc:
        return response_json({'message': exc.messages[0]}, status=400)

    users = list(eligible_users(channel, purpose, destination)[:2])
    generic_message = verification_sent_message(channel)
    if not users:
        return response_json({'message': generic_message})

    now = timezone.now()
    VerificationCode.objects.filter(created_at__lt=now - timedelta(days=1)).delete()
    recent = VerificationCode.objects.filter(
        channel=channel,
        purpose=purpose,
        destination=destination,
    ).order_by('-created_at').first()
    if recent:
        retry_after = settings.VERIFICATION_CODE_COOLDOWN_SECONDS - int((now - recent.created_at).total_seconds())
        if retry_after > 0:
            return response_json(
                {'message': f'请等待 {retry_after} 秒后再次发送。', 'retry_after': retry_after},
                status=429,
            )

    today_count = VerificationCode.objects.filter(
        channel=channel,
        destination=destination,
        created_at__gte=now - timedelta(days=1),
    ).count()
    if today_count >= settings.VERIFICATION_CODE_DAILY_LIMIT:
        return response_json({'message': '今天发送次数过多，请明天再试。'}, status=429)

    code = f'{secrets.randbelow(1_000_000):06d}'
    verification = VerificationCode.objects.create(
        channel=channel,
        purpose=purpose,
        destination=destination,
        code_hash=make_password(code),
        request_ip=client_ip(request),
        expires_at=now + timedelta(minutes=settings.VERIFICATION_CODE_EXPIRE_MINUTES),
    )
    try:
        deliver_code(channel, destination, purpose, code)
    except Exception as exc:
        verification.delete()
        record_event(
            request,
            UserSecurityEvent.Event.VERIFICATION_CODE_SENT,
            user=users[0],
            details={'channel': channel, 'purpose': purpose, 'sent': False, 'error': str(exc)[:300]},
        )
        return response_json({'message': '验证码发送失败，请稍后重试。'}, status=503)

    record_event(
        request,
        UserSecurityEvent.Event.VERIFICATION_CODE_SENT,
        user=users[0],
        details={'channel': channel, 'purpose': purpose, 'sent': True},
    )
    result = {
        'message': generic_message,
        'expires_in': settings.VERIFICATION_CODE_EXPIRE_MINUTES * 60,
        'retry_after': settings.VERIFICATION_CODE_COOLDOWN_SECONDS,
    }
    if settings.DEBUG and 'console' in settings.EMAIL_BACKEND:
        result['debug_code'] = code
    return response_json(result)


def find_verification_code(channel, purpose, destination, code):
    verification = VerificationCode.objects.filter(
        channel=channel,
        purpose=purpose,
        destination=destination,
        consumed_at__isnull=True,
    ).order_by('-created_at').first()
    now = timezone.now()
    if not verification or verification.expires_at <= now:
        return None, '验证码无效或已经过期，请重新获取。'
    if verification.failed_attempts >= settings.VERIFICATION_CODE_MAX_ATTEMPTS:
        return None, '验证码错误次数过多，请重新获取。'
    if not check_password(str(code or '').strip(), verification.code_hash):
        verification.failed_attempts += 1
        if verification.failed_attempts >= settings.VERIFICATION_CODE_MAX_ATTEMPTS:
            verification.consumed_at = now
        verification.save(update_fields=['failed_attempts', 'consumed_at'])
        return None, '验证码不正确。'
    return verification, ''


def consume_verification_code(verification):
    verification.consumed_at = timezone.now()
    verification.save(update_fields=['consumed_at'])


@ensure_csrf_cookie
@require_GET
def session_detail(request):
    return response_json({
        'authenticated': request.user.is_authenticated,
        'user': serialize_user(request.user) if request.user.is_authenticated else None,
    })


@require_POST
def send_verification_code(request):
    payload = request_payload(request)
    channel = str(payload.get('channel', '')).strip()
    purpose = str(payload.get('purpose', '')).strip()
    return create_verification_code(request, channel, purpose, payload.get('destination', ''))


@require_POST
def login_user(request):
    payload = request_payload(request)
    method = str(payload.get('method', 'password')).strip()
    if method != 'password':
        return response_json({'message': '只支持用户名和密码登录。'}, status=400)

    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', ''))
    if not username or not password:
        return response_json({'message': '请输入用户名和密码。'}, status=400)
    if is_login_blocked(request, username):
        record_event(request, UserSecurityEvent.Event.LOGIN_BLOCKED, username=username)
        return response_json({'message': '登录失败次数过多，请 15 分钟后再试。'}, status=429)

    user = authenticate(request, username=username, password=password)
    if user is None:
        record_event(request, UserSecurityEvent.Event.LOGIN_FAILED, username=username, details={'method': 'password'})
        return response_json({'message': '用户名或密码不正确。'}, status=401)
    if not user.is_active:
        record_event(request, UserSecurityEvent.Event.LOGIN_FAILED, user=user, details={'method': 'password'})
        return response_json({'message': '该账号已被停用，请联系管理员。'}, status=403)

    login(request, user)
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if payload.get('remember_me') else 0)
    record_event(request, UserSecurityEvent.Event.LOGIN_SUCCEEDED, user=user, details={'method': 'password'})
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
    try:
        validate_email(email)
    except ValidationError:
        errors['email'] = ['请输入正确的邮箱地址。']
    else:
        if User.objects.filter(email__iexact=email).exists():
            errors['email'] = ['该邮箱已经注册，请直接登录或找回用户名。']
    if errors:
        return response_json({'message': '请检查注册信息。', 'field_errors': errors}, status=400)

    try:
        with transaction.atomic():
            user = form.save(commit=False)
            user.email = email
            user.save()
            Profile.objects.create(user=user, nickname=user.username)
            record_event(request, UserSecurityEvent.Event.REGISTERED, user=user)
    except IntegrityError:
        return response_json({'message': '用户名或邮箱已经被使用。'}, status=400)

    login(request, user)
    request.session.set_expiry(0)
    record_event(request, UserSecurityEvent.Event.LOGIN_SUCCEEDED, user=user, details={'source': 'registration'})
    return response_json({'authenticated': True, 'user': serialize_user(user)}, status=201)


@require_POST
def recover_account(request):
    payload = request_payload(request)
    try:
        email = normalize_destination(VerificationCode.Channel.EMAIL, payload.get('email', ''))
    except ValidationError:
        return response_json({'message': '请输入正确的注册邮箱。'}, status=400)
    verification, error = find_verification_code(
        VerificationCode.Channel.EMAIL,
        VerificationCode.Purpose.ACCOUNT_RECOVERY,
        email,
        payload.get('code', ''),
    )
    if not verification:
        return response_json({'message': error}, status=400)

    users = list(User.objects.filter(email__iexact=email, is_active=True).order_by('date_joined')[:5])
    if not users:
        return response_json({'message': '验证码无效或已经过期，请重新获取。'}, status=400)
    consume_verification_code(verification)
    account_names = [user.username for user in users]
    record_event(request, UserSecurityEvent.Event.ACCOUNT_RECOVERY, user=users[0])
    return response_json({'message': f'你的用户名：{"、".join(account_names)}', 'usernames': account_names})


@require_POST
def request_password_reset(request):
    payload = request_payload(request)
    return create_verification_code(
        request,
        VerificationCode.Channel.EMAIL,
        VerificationCode.Purpose.PASSWORD_RESET,
        payload.get('email', ''),
    )


def confirm_password_with_email_code(request, payload):
    try:
        email = normalize_destination(VerificationCode.Channel.EMAIL, payload.get('email', ''))
    except ValidationError:
        return response_json({'message': '请输入正确的注册邮箱。'}, status=400)
    verification, error = find_verification_code(
        VerificationCode.Channel.EMAIL,
        VerificationCode.Purpose.PASSWORD_RESET,
        email,
        payload.get('code', ''),
    )
    if not verification:
        return response_json({'message': error}, status=400)

    user = User.objects.filter(email__iexact=email, is_active=True).order_by('date_joined').first()
    if not user:
        return response_json({'message': '验证码无效或已经过期，请重新获取。'}, status=400)
    form = SetPasswordForm(user, {
        'new_password1': str(payload.get('password1', '')),
        'new_password2': str(payload.get('password2', '')),
    })
    if not form.is_valid():
        return response_json({'message': '请检查新密码。', 'field_errors': form_errors(form)}, status=400)

    form.save()
    consume_verification_code(verification)
    record_event(request, UserSecurityEvent.Event.PASSWORD_RESET_COMPLETED, user=user)
    return response_json({'message': '密码已重置，请使用新密码登录。'})


def confirm_password_with_legacy_link(request, payload):
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
        return response_json({'message': '请检查新密码。', 'field_errors': form_errors(form)}, status=400)
    form.save()
    record_event(request, UserSecurityEvent.Event.PASSWORD_RESET_COMPLETED, user=user)
    return response_json({'message': '密码已重置，请使用新密码登录。'})


@require_POST
def confirm_password_reset(request):
    payload = request_payload(request)
    if payload.get('email') or payload.get('code'):
        return confirm_password_with_email_code(request, payload)
    return confirm_password_with_legacy_link(request, payload)


def csrf_failure(request, reason=''):
    return response_json({'message': '页面安全校验已过期，请刷新页面后重试。'}, status=403)
