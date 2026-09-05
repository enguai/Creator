from __future__ import annotations

import hashlib
import json
import secrets

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import GuardLicense, GuardLicenseDevice


MAX_BODY_BYTES = 16 * 1024


def _json_error(message, status=400, code='invalid_request'):
    return JsonResponse(
        {'ok': False, 'code': code, 'message': message},
        status=status,
        json_dumps_params={'ensure_ascii': False},
    )


def _read_payload(request):
    if len(request.body) > MAX_BODY_BYTES:
        raise ValueError('请求内容过大。')
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('请求格式不正确。') from exc
    if not isinstance(data, dict):
        raise ValueError('请求格式不正确。')
    return data


def _client_ip(request):
    forwarded = request.headers.get('X-Forwarded-For', '')
    return (forwarded.split(',', 1)[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None


def _license_problem(license_obj):
    if license_obj.status == GuardLicense.Status.SUSPENDED:
        return 'suspended', '此授权已被暂停，请联系管理员。'
    if license_obj.status == GuardLicense.Status.REVOKED:
        return 'revoked', '此授权已被撤销，请联系管理员。'
    if license_obj.expires_at and license_obj.expires_at <= timezone.now():
        return 'expired', '此授权已经到期，请联系管理员续期。'
    return None


def _license_payload(license_obj):
    return {
        'authorization_id': str(license_obj.id),
        'licensee_name': license_obj.licensee_name,
        'expires_at': license_obj.expires_at.isoformat() if license_obj.expires_at else None,
        'max_devices': license_obj.max_devices,
        'offline_grace_days': license_obj.offline_grace_days,
        'server_time': timezone.now().isoformat(),
    }


@csrf_exempt
@require_POST
def activate_license(request):
    try:
        payload = _read_payload(request)
    except ValueError as exc:
        return _json_error(str(exc))
    code = str(payload.get('activation_code', '')).strip().upper()
    machine_code = str(payload.get('machine_code', '')).strip().lower()
    app_version = str(payload.get('app_version', '')).strip()[:30]
    if not code or len(machine_code) != 64:
        return _json_error('请输入有效的激活码，并确认机器码完整。')

    with transaction.atomic():
        try:
            license_obj = GuardLicense.objects.select_for_update().get(activation_code=code)
        except GuardLicense.DoesNotExist:
            return _json_error('激活码不存在，请检查后重新输入。', 404, 'not_found')
        if problem := _license_problem(license_obj):
            return _json_error(problem[1], 403, problem[0])

        device = GuardLicenseDevice.objects.filter(
            license=license_obj,
            machine_code=machine_code,
        ).first()
        if device is None or device.is_revoked:
            used = license_obj.devices.filter(is_revoked=False).count()
            if used >= license_obj.max_devices:
                return _json_error(
                    '此激活码绑定的电脑数量已达到上限，请先在管理后台解绑旧电脑。',
                    403,
                    'device_limit',
                )
            if device is None:
                device = GuardLicenseDevice(license=license_obj, machine_code=machine_code)

        raw_token = secrets.token_urlsafe(32)
        device.token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
        device.app_version = app_version
        device.is_revoked = False
        device.last_ip = _client_ip(request)
        device.save()

    return JsonResponse(
        {'ok': True, 'device_token': raw_token, 'license': _license_payload(license_obj)},
        json_dumps_params={'ensure_ascii': False},
    )


@csrf_exempt
@require_POST
def validate_license(request):
    try:
        payload = _read_payload(request)
    except ValueError as exc:
        return _json_error(str(exc))
    machine_code = str(payload.get('machine_code', '')).strip().lower()
    raw_token = str(payload.get('device_token', '')).strip()
    app_version = str(payload.get('app_version', '')).strip()[:30]
    if len(machine_code) != 64 or not raw_token:
        return _json_error('本机授权凭据不完整，请重新激活。', 401, 'credentials_missing')

    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    try:
        device = GuardLicenseDevice.objects.select_related('license').get(
            machine_code=machine_code,
            token_hash=token_hash,
        )
    except GuardLicenseDevice.DoesNotExist:
        return _json_error('本机授权凭据已失效，请重新激活。', 401, 'credentials_invalid')
    if device.is_revoked:
        return _json_error('此电脑已在管理后台解绑，请重新激活。', 403, 'device_revoked')
    if problem := _license_problem(device.license):
        return _json_error(problem[1], 403, problem[0])

    device.app_version = app_version
    device.last_ip = _client_ip(request)
    device.save(update_fields=['app_version', 'last_ip', 'last_seen_at'])
    return JsonResponse(
        {'ok': True, 'license': _license_payload(device.license)},
        json_dumps_params={'ensure_ascii': False},
    )
