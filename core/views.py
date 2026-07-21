import hmac
import json
import os
import uuid
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .form_automation import (
    FORM_ASSET_LABELS,
    form_automation_capabilities,
    generate_form_automation_workbook,
    setting_or_env as form_setting_or_env,
)
from .models import FormAutomationAsset, FormAutomationJob, PayrollJob
from .payroll import FILE_LABELS


def api_response(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


def setting_or_env(name, default=''):
    return getattr(settings, name, None) or form_setting_or_env(name, default)


def form_automation_backend():
    return setting_or_env('FORM_AUTOMATION_BACKEND', 'sync').strip().lower() or 'sync'


def worker_token():
    return setting_or_env('FORM_AUTOMATION_WORKER_TOKEN', '').strip()


def allow_form_review_fallback():
    return setting_or_env('FORM_AUTOMATION_ALLOW_REVIEW_FALLBACK', '').strip().lower() in {
        '1',
        'true',
        'yes',
        'on',
    }


def payroll_backend():
    """Payroll follows the same Windows Codex Worker pipeline as form automation."""
    return setting_or_env('PAYROLL_BACKEND', form_automation_backend()).strip().lower() or 'sync'


def require_worker_token(request):
    configured_token = worker_token()
    provided_token = (
        request.headers.get('X-Creator-Worker-Token')
        or request.POST.get('worker_token', '')
        or request.GET.get('worker_token', '')
    )
    if not configured_token:
        return False
    return hmac.compare_digest(str(configured_token), str(provided_token or ''))


def parse_json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode('utf-8'))
    except Exception:
        return {}


def positive_int_setting(name, default, minimum=1, maximum=86400):
    try:
        value = int(setting_or_env(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def worker_lease_seconds():
    return positive_int_setting('AUTOMATION_WORKER_LEASE_SECONDS', 180, minimum=60, maximum=3600)


def worker_max_attempts():
    return positive_int_setting('AUTOMATION_WORKER_MAX_ATTEMPTS', 3, minimum=1, maximum=10)


def request_worker_id(request, body=None):
    payload = body if isinstance(body, dict) else parse_json_body(request)
    value = payload.get('worker_id') or request.headers.get('X-Creator-Worker-Id') or 'unknown-worker'
    return str(value)[:120]


def request_claim_token(request, body=None):
    payload = body if isinstance(body, dict) else {}
    value = request.POST.get('claim_token') or payload.get('claim_token')
    return str(value or '').strip()


def worker_claim_matches(job, claim_token):
    return (
        job.status == job.Status.RUNNING
        and job.claim_token is not None
        and hmac.compare_digest(str(job.claim_token), str(claim_token or ''))
    )


def stale_worker_jobs_to_queue(model):
    now = timezone.now()
    stale_jobs = list(
        model.objects.filter(
            status=model.Status.RUNNING,
            lease_expires_at__lte=now,
        ).order_by('lease_expires_at')[:100]
    )
    for job in stale_jobs:
        summary = dict(job.summary or {})
        summary['worker_recovered_at'] = timezone.localtime(now).isoformat()
        summary['worker_recovery_reason'] = 'Worker 心跳超时，任务租约已失效。'
        base_filter = model.objects.filter(
            id=job.id,
            status=model.Status.RUNNING,
            claim_token=job.claim_token,
            lease_expires_at__lte=now,
        )
        if job.attempt_count >= worker_max_attempts():
            base_filter.update(
                status=model.Status.FAILED,
                progress_message='Worker 多次中断，任务已失败',
                error_message=f'Worker 心跳超时，已达到最大重试次数（{worker_max_attempts()} 次）。',
                summary=summary,
                worker_id='',
                claim_token=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
        else:
            base_filter.update(
                status=model.Status.PENDING,
                progress=0,
                progress_message='Worker 中断，等待自动重试',
                error_message='',
                summary=summary,
                worker_id='',
                claim_token=None,
                lease_expires_at=None,
                started_at=None,
                updated_at=now,
            )


def claim_next_worker_job(model, worker_id):
    stale_worker_jobs_to_queue(model)
    now = timezone.now()
    lease_expires_at = now + timedelta(seconds=worker_lease_seconds())

    for _attempt in range(20):
        candidate = (
            model.objects.filter(status=model.Status.PENDING)
            .order_by('created_at')
            .values('id')
            .first()
        )
        if not candidate:
            return None

        claim_token = uuid.uuid4()
        claimed = model.objects.filter(
            id=candidate['id'],
            status=model.Status.PENDING,
        ).update(
            status=model.Status.RUNNING,
            progress=5,
            progress_message='Worker 已领取任务',
            worker_id=worker_id,
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
            attempt_count=F('attempt_count') + 1,
            started_at=now,
            finished_at=None,
            error_message='',
            updated_at=now,
        )
        if not claimed:
            continue

        job = model.objects.get(id=candidate['id'])
        summary = dict(job.summary or {})
        summary.update(
            {
                'mode': 'codex-skill-worker',
                'backend': 'codex_worker',
                'worker_claimed_at': timezone.localtime(now).isoformat(),
                'worker': worker_id,
                'attempt': job.attempt_count,
            }
        )
        model.objects.filter(id=job.id, claim_token=claim_token).update(summary=summary)
        job.summary = summary
        return job

    return None


def update_worker_heartbeat(request, model, serializer, job_id):
    if not require_worker_token(request):
        return api_response({'error': 'worker_unauthorized', 'message': 'Worker token 未配置或不正确。'}, status=403)

    body = parse_json_body(request)
    claim_token = request_claim_token(request, body)
    try:
        requested_progress = int(body.get('progress', 0))
    except (TypeError, ValueError):
        return api_response({'error': 'invalid_progress', 'message': '进度必须是 0 到 99 的整数。'}, status=400)

    with transaction.atomic():
        job = get_object_or_404(model.objects.select_for_update(), id=job_id)
        if not worker_claim_matches(job, claim_token):
            return api_response(
                {'error': 'worker_claim_expired', 'message': '任务已被重新分配或已经结束，请停止处理当前副本。'},
                status=409,
            )

        job.progress = max(job.progress, min(99, max(1, requested_progress)))
        job.progress_message = str(body.get('message') or job.progress_message)[:200]
        job.lease_expires_at = timezone.now() + timedelta(seconds=worker_lease_seconds())
        job.save(update_fields=['progress', 'progress_message', 'lease_expires_at', 'updated_at'])
    return api_response(serializer(job))


def worker_tracking_payload(job):
    return {
        'progress': job.progress,
        'progress_message': job.progress_message,
        'worker_id': job.worker_id,
        'attempt_count': job.attempt_count,
        'started_at': job.started_at.isoformat() if job.started_at else '',
        'finished_at': job.finished_at.isoformat() if job.finished_at else '',
    }


def worker_asset_payload(request, asset):
    return {
        'id': asset.id,
        'group': asset.group,
        'label': FORM_ASSET_LABELS.get(asset.group, asset.group),
        'name': asset.original_name,
        'size': asset.size,
        'download_url': request.build_absolute_uri(
            reverse('form-automation-worker-asset-download', args=[asset.id])
        ),
    }


def worker_job_payload(request, job):
    return {
        'job': serialize_form_automation_job(job),
        'assets': [
            worker_asset_payload(request, asset)
            for asset in job.assets.all()
        ],
        'complete_url': request.build_absolute_uri(
            reverse('form-automation-worker-job-complete', args=[job.id])
        ),
        'fail_url': request.build_absolute_uri(
            reverse('form-automation-worker-job-fail', args=[job.id])
        ),
        'heartbeat_url': request.build_absolute_uri(
            reverse('form-automation-worker-job-heartbeat', args=[job.id])
        ),
        'claim_token': str(job.claim_token),
    }


def payroll_worker_asset_payload(request, job, field_name, label):
    file_field = getattr(job, field_name)
    return {
        'group': field_name,
        'label': label,
        'name': file_field.name.split('/')[-1],
        'size': file_field.size,
        'download_url': request.build_absolute_uri(
            reverse('payroll-worker-asset-download', args=[job.id, field_name])
        ),
    }


def payroll_worker_job_payload(request, job):
    return {
        'job': serialize_payroll_job(job),
        'assets': [
            payroll_worker_asset_payload(request, job, field_name, label)
            for field_name, label in FILE_LABELS
        ],
        'complete_url': request.build_absolute_uri(
            reverse('payroll-worker-job-complete', args=[job.id])
        ),
        'fail_url': request.build_absolute_uri(
            reverse('payroll-worker-job-fail', args=[job.id])
        ),
        'heartbeat_url': request.build_absolute_uri(
            reverse('payroll-worker-job-heartbeat', args=[job.id])
        ),
        'claim_token': str(job.claim_token),
    }


def serialize_payroll_job(job):
    download_url = ''
    if job.status == PayrollJob.Status.SUCCESS and job.result_file:
        download_url = reverse('payroll-job-download', args=[job.id])

    return {
        'id': str(job.id),
        'room_type': job.room_type,
        'week_start': job.week_start.isoformat() if job.week_start else '',
        'week_end': job.week_end.isoformat() if job.week_end else '',
        'status': job.status,
        'error_message': job.error_message,
        'download_url': download_url,
        'summary': job.summary,
        'created_at': job.created_at.isoformat(),
        'updated_at': job.updated_at.isoformat(),
        **worker_tracking_payload(job),
        'files': [
            {
                'field': field_name,
                'label': label,
                'name': getattr(job, field_name).name.split('/')[-1],
                'size': getattr(job, field_name).size,
            }
            for field_name, label in FILE_LABELS
            if getattr(job, field_name)
        ],
    }


def serialize_form_automation_job(job):
    download_url = ''
    if job.status == FormAutomationJob.Status.SUCCESS and job.result_file:
        download_url = reverse('form-automation-job-download', args=[job.id])

    assets = list(job.assets.all())
    grouped_counts = {}
    for asset in assets:
        grouped_counts[asset.group] = grouped_counts.get(asset.group, 0) + 1

    return {
        'id': str(job.id),
        'form_type': job.form_type,
        'status': job.status,
        'error_message': job.error_message,
        'download_url': download_url,
        'summary': job.summary,
        'asset_counts': grouped_counts,
        'created_at': job.created_at.isoformat(),
        'updated_at': job.updated_at.isoformat(),
        **worker_tracking_payload(job),
        'files': [
            {
                'group': asset.group,
                'label': FORM_ASSET_LABELS.get(asset.group, asset.group),
                'name': asset.original_name,
                'size': asset.size,
            }
            for asset in assets
        ],
    }


def form_automation_result_filename(job):
    completed_at = job.finished_at or job.updated_at or timezone.now()
    local_date = timezone.localtime(completed_at, ZoneInfo('Asia/Shanghai'))
    prefix = '费用报销表' if job.form_type == FormAutomationJob.FormType.EXPENSE else '采购申请表'
    return f'{prefix}{local_date.month}.{local_date.day}.xlsx'


class CloudTaskLookupError(RuntimeError):
    pass


def get_cloud_worker_task(request, job_id):
    base_url = setting_or_env('CREATOR_CLOUD_SERVER_URL', '').strip().rstrip('/')
    if not base_url or urlparse(base_url).netloc.lower() == request.get_host().lower():
        return None

    task_url = f'{base_url}/api/tasks/{job_id}/'
    try:
        with urlopen(Request(task_url, headers={'Accept': 'application/json'}), timeout=8) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise CloudTaskLookupError(f'云端任务接口返回 HTTP {exc.code}') from exc
    except (OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloudTaskLookupError('无法连接云端任务接口') from exc

    download_url = payload.get('download_url', '')
    if download_url:
        payload['download_url'] = urljoin(f'{base_url}/', download_url)
    payload['task_source'] = 'cloud'
    return payload


@require_GET
def get_worker_task(request, job_id):
    try:
        job = FormAutomationJob.objects.prefetch_related('assets').get(id=job_id)
        serialized = serialize_form_automation_job(job)
        task_type = 'form_automation'
        task_label = '费用报销表' if job.form_type == FormAutomationJob.FormType.EXPENSE else '采购申请表'
    except FormAutomationJob.DoesNotExist:
        try:
            job = PayrollJob.objects.get(id=job_id)
        except PayrollJob.DoesNotExist:
            try:
                cloud_task = get_cloud_worker_task(request, job_id)
            except CloudTaskLookupError as exc:
                return api_response(
                    {'error': 'cloud_task_lookup_failed', 'message': f'{exc}，请确认云端服务可访问。'},
                    status=502,
                )
            if cloud_task is not None:
                return api_response(cloud_task)
            return api_response(
                {'error': 'task_not_found', 'message': '本地和云端都没有找到这个任务，请检查任务 ID 是否完整。'},
                status=404,
            )
        serialized = serialize_payroll_job(job)
        task_type = 'payroll'
        room_labels = {
            'z4-neck': 'Z4 颈膜直播间',
            'z2-eye': 'Z2 眼膜直播间',
            'z3-polish': 'Z3 抛光直播间',
        }
        task_label = f"兼职薪资计算 · {room_labels.get(job.room_type, job.room_type)}"

    status_labels = {
        'pending': '等待处理',
        'running': '正在处理',
        'success': '处理成功',
        'failed': '处理失败',
    }
    outcome = 'succeed' if job.status == job.Status.SUCCESS else 'failed' if job.status == job.Status.FAILED else 'processing'
    return api_response(
        {
            'id': str(job.id),
            'task_type': task_type,
            'task_label': task_label,
            'status': job.status,
            'status_label': status_labels.get(job.status, job.status),
            'outcome': outcome,
            'progress': job.progress,
            'progress_message': job.progress_message,
            'attempt_count': job.attempt_count,
            'worker_id': job.worker_id,
            'created_at': job.created_at.isoformat(),
            'updated_at': job.updated_at.isoformat(),
            'started_at': job.started_at.isoformat() if job.started_at else '',
            'finished_at': job.finished_at.isoformat() if job.finished_at else '',
            'error_message': job.error_message,
            'download_url': serialized['download_url'],
            'files': serialized['files'],
            'task_source': 'local',
        }
    )


@require_GET
def payroll_health(_request):
    return api_response(
        {
            'ok': True,
            'service': 'creator-payroll',
            'message': '兼职薪资计算后端已连接。',
            'capabilities': {
                'backend': payroll_backend(),
                'worker_token_configured': bool(worker_token()),
                'skill': 'live-payroll',
            },
            'server_time': timezone.localtime(timezone.now()).isoformat(),
            'upload_limit_mb': settings.DATA_UPLOAD_MAX_MEMORY_SIZE // 1024 // 1024,
        }
    )


@require_GET
def form_automation_health(_request):
    capabilities = form_automation_capabilities()
    capabilities.update(
        {
            'backend': form_automation_backend(),
            'worker_token_configured': bool(worker_token()),
        }
    )
    return api_response(
        {
            'ok': True,
            'service': 'creator-form-automation',
            'message': '报销表格自动化后端已连接。',
            'capabilities': capabilities,
            'server_time': timezone.localtime(timezone.now()).isoformat(),
            'upload_limit_mb': settings.DATA_UPLOAD_MAX_MEMORY_SIZE // 1024 // 1024,
        }
    )


@csrf_exempt
@require_POST
def create_payroll_job(request):
    try:
        uploaded_files = request.FILES
        post_data = request.POST
    except RequestDataTooBig:
        return api_response(
            {
                'error': 'request_too_large',
                'message': '上传文件超过服务器当前限制，请压缩图片或提高服务器上传限制后再试。',
            },
            status=413,
        )
    except Exception as exc:
        return api_response(
            {
                'error': 'upload_parse_failed',
                'message': '服务器无法读取本次上传内容，请确认文件没有损坏后重新提交。',
                'detail': str(exc) if settings.DEBUG else '',
            },
            status=400,
        )

    required_files = [field_name for field_name, _label in FILE_LABELS]
    missing_files = [field_name for field_name in required_files if field_name not in uploaded_files]

    if missing_files:
        label_map = dict(FILE_LABELS)
        return api_response(
            {
                'error': 'missing_files',
                'message': '请上传全部四个薪资计算文件。',
                'missing_files': missing_files,
                'missing_file_labels': [label_map[field_name] for field_name in missing_files],
            },
            status=400,
        )

    empty_files = [field_name for field_name in required_files if uploaded_files[field_name].size == 0]
    if empty_files:
        label_map = dict(FILE_LABELS)
        return api_response(
            {
                'error': 'empty_files',
                'message': '有文件大小为 0，请重新选择后再提交。',
                'empty_files': empty_files,
                'empty_file_labels': [label_map[field_name] for field_name in empty_files],
            },
            status=400,
        )

    week_start = None
    week_end = None
    week_start_raw = post_data.get('week_start', '').strip()
    week_end_raw = post_data.get('week_end', '').strip()
    if week_start_raw:
        week_start = parse_date(week_start_raw)
        if week_start is None:
            return api_response(
                {
                    'error': 'invalid_week_start',
                    'message': '薪资周开始日期格式不正确，请使用 YYYY-MM-DD。',
                },
                status=400,
            )
    if week_end_raw:
        week_end = parse_date(week_end_raw)
        if week_end is None:
            return api_response(
                {
                    'error': 'invalid_week_end',
                    'message': '薪资计算周期结束日期格式不正确，请使用 YYYY-MM-DD。',
                },
                status=400,
            )

    if week_start and week_end and week_end < week_start:
        return api_response(
            {
                'error': 'invalid_payroll_period',
                'message': '薪资计算周期的结束日期不能早于开始日期。',
            },
            status=400,
        )

    room_type = post_data.get('room_type', '').strip()
    supported_rooms = {'z4-neck', 'z2-eye', 'z3-polish'}
    if room_type not in supported_rooms:
        return api_response(
            {
                'error': 'invalid_room_type',
                'message': '请选择 Z4 颈膜、Z2 眼膜或 Z3 抛光直播间。',
            },
            status=400,
        )

    backend = payroll_backend()
    if backend != 'codex_worker' or not worker_token():
        return api_response(
            {
                'error': 'payroll_backend_not_ready',
                'message': (
                    '兼职薪资计算尚未启用 Codex Worker。为避免生成不可靠的测试文档，'
                    '本次提交未执行。请先启动 Windows Worker 后重试。'
                ),
                'backend': backend,
            },
            status=503,
        )

    try:
        job = PayrollJob.objects.create(
            room_type=room_type,
            week_start=week_start,
            week_end=week_end,
            host_schedule=uploaded_files['host_schedule'],
            controller_schedule=uploaded_files['controller_schedule'],
            trial_schedule=uploaded_files['trial_schedule'],
            host_data=uploaded_files['host_data'],
            status=PayrollJob.Status.PENDING,
            summary={
                'mode': 'codex-skill-worker',
                'backend': 'codex_worker',
                'skill': 'live-payroll',
                'message': '任务已进入 Codex Worker 队列；Windows Worker 将按 live-payroll skill 生成正式薪资表。',
            },
        )
    except Exception as exc:
        return api_response(
            {
                'error': 'job_create_failed',
                'message': '服务器保存上传文件失败，请检查磁盘空间或 media 目录权限。',
                'detail': str(exc) if settings.DEBUG else '',
            },
            status=500,
        )

    return api_response(serialize_payroll_job(job), status=201)


@require_GET
def get_payroll_job(_request, job_id):
    job = get_object_or_404(PayrollJob, id=job_id)
    return api_response(serialize_payroll_job(job))


@require_GET
def download_payroll_result(_request, job_id):
    job = get_object_or_404(PayrollJob, id=job_id)

    if job.status != PayrollJob.Status.SUCCESS or not job.result_file:
        raise Http404('Payroll result is not ready.')

    try:
        response = FileResponse(
            job.result_file.open('rb'),
            as_attachment=True,
            filename=job.result_file.name.split('/')[-1],
        )
    except FileNotFoundError as exc:
        raise Http404('Payroll result file was not found.') from exc

    return response


@csrf_exempt
@require_POST
def worker_next_payroll_job(request):
    if not require_worker_token(request):
        return api_response(
            {
                'error': 'worker_unauthorized',
                'message': 'Worker token 未配置或不正确。',
            },
            status=403,
        )

    body = parse_json_body(request)
    job = claim_next_worker_job(PayrollJob, request_worker_id(request, body))
    if not job:
        return api_response({'ok': True, 'job': None})

    return api_response(payroll_worker_job_payload(request, job))


@csrf_exempt
@require_POST
def worker_heartbeat_payroll_job(request, job_id):
    return update_worker_heartbeat(request, PayrollJob, serialize_payroll_job, job_id)


@require_GET
def worker_download_payroll_asset(request, job_id, field_name):
    if not require_worker_token(request):
        return api_response(
            {
                'error': 'worker_unauthorized',
                'message': 'Worker token 未配置或不正确。',
            },
            status=403,
        )

    label_map = dict(FILE_LABELS)
    if field_name not in label_map:
        raise Http404('Payroll asset field does not exist.')

    job = get_object_or_404(PayrollJob, id=job_id)
    file_field = getattr(job, field_name)
    try:
        return FileResponse(
            file_field.open('rb'),
            as_attachment=True,
            filename=file_field.name.split('/')[-1],
        )
    except FileNotFoundError as exc:
        raise Http404('Payroll source file was not found.') from exc


def update_payroll_summary_from_worker(job, raw_summary):
    summary = dict(job.summary or {})
    if isinstance(raw_summary, dict):
        summary.update(raw_summary)
    elif isinstance(raw_summary, str) and raw_summary.strip():
        try:
            parsed_summary = json.loads(raw_summary)
            if isinstance(parsed_summary, dict):
                summary.update(parsed_summary)
        except json.JSONDecodeError:
            summary['worker_summary_parse_error'] = raw_summary[:500]
    return summary


@csrf_exempt
@require_POST
def worker_complete_payroll_job(request, job_id):
    if not require_worker_token(request):
        return api_response(
            {
                'error': 'worker_unauthorized',
                'message': 'Worker token 未配置或不正确。',
            },
            status=403,
        )

    result_file = request.FILES.get('result_file')
    if not result_file:
        return api_response(
            {
                'error': 'missing_result_file',
                'message': '请上传 Worker 生成的 result_file。',
            },
            status=400,
        )

    claim_token = request_claim_token(request)
    with transaction.atomic():
        job = get_object_or_404(PayrollJob.objects.select_for_update(), id=job_id)
        if job.status == PayrollJob.Status.SUCCESS and job.result_file:
            return api_response(serialize_payroll_job(job))
        if not worker_claim_matches(job, claim_token):
            return api_response(
                {'error': 'worker_claim_expired', 'message': '任务已被重新分配或已经结束，当前结果不会写入。'},
                status=409,
            )

        summary = update_payroll_summary_from_worker(job, request.POST.get('summary', ''))
        summary.update(
            {
                'mode': 'codex-skill-worker',
                'backend': 'codex_worker',
                'skill': 'live-payroll',
                'worker_completed_at': timezone.localtime(timezone.now()).isoformat(),
                'result_filename': result_file.name,
            }
        )
        job.result_file.save(result_file.name, result_file, save=False)
        job.summary = summary
        job.status = PayrollJob.Status.SUCCESS
        job.progress = 100
        job.progress_message = '处理成功'
        job.claim_token = None
        job.lease_expires_at = None
        job.finished_at = timezone.now()
        job.error_message = ''
        job.save(
            update_fields=[
                'summary', 'result_file', 'status', 'progress', 'progress_message',
                'claim_token', 'lease_expires_at', 'finished_at', 'error_message', 'updated_at',
            ]
        )
    return api_response(serialize_payroll_job(job))


@csrf_exempt
@require_POST
def worker_fail_payroll_job(request, job_id):
    if not require_worker_token(request):
        return api_response(
            {
                'error': 'worker_unauthorized',
                'message': 'Worker token 未配置或不正确。',
            },
            status=403,
        )

    body = parse_json_body(request)
    error_message = (
        request.POST.get('error_message')
        or body.get('error_message')
        or 'Codex Worker 生成失败。'
    )
    claim_token = request_claim_token(request, body)
    with transaction.atomic():
        job = get_object_or_404(PayrollJob.objects.select_for_update(), id=job_id)
        if job.status in {PayrollJob.Status.SUCCESS, PayrollJob.Status.FAILED}:
            return api_response(serialize_payroll_job(job))
        if not worker_claim_matches(job, claim_token):
            return api_response(
                {'error': 'worker_claim_expired', 'message': '任务已被重新分配或已经结束，当前失败信息不会写入。'},
                status=409,
            )

        raw_summary = request.POST.get('summary') or body.get('summary', '')
        summary = update_payroll_summary_from_worker(job, raw_summary)
        summary.update(
            {
                'mode': 'codex-skill-worker',
                'backend': 'codex_worker',
                'skill': 'live-payroll',
                'worker_failed_at': timezone.localtime(timezone.now()).isoformat(),
            }
        )
        job.summary = summary
        job.status = PayrollJob.Status.FAILED
        job.progress_message = '处理失败'
        job.claim_token = None
        job.lease_expires_at = None
        job.finished_at = timezone.now()
        job.error_message = str(error_message)[:5000]
        job.save(
            update_fields=[
                'summary', 'status', 'progress_message', 'claim_token', 'lease_expires_at',
                'finished_at', 'error_message', 'updated_at',
            ]
        )
    return api_response(serialize_payroll_job(job))


@csrf_exempt
@require_POST
def create_form_automation_job(request):
    try:
        uploaded_files = request.FILES
        post_data = request.POST
    except RequestDataTooBig:
        return api_response(
            {
                'error': 'request_too_large',
                'message': '上传文件超过服务器当前限制，请减少文件数量或提高服务器上传限制后再试。',
            },
            status=413,
        )
    except Exception as exc:
        return api_response(
            {
                'error': 'upload_parse_failed',
                'message': '服务器无法读取本次上传内容，请确认文件没有损坏后重新提交。',
                'detail': str(exc) if settings.DEBUG else '',
            },
            status=400,
        )

    form_type = post_data.get('form_type', '').strip()
    if form_type not in FormAutomationJob.FormType.values:
        return api_response(
            {
                'error': 'invalid_form_type',
                'message': '请选择费用报销表或采购申请表。',
            },
            status=400,
        )

    required_groups = (
        ('purchase_screenshots', 'invoices')
        if form_type == FormAutomationJob.FormType.EXPENSE
        else ('reference_images', 'link_txt')
    )
    missing_groups = [
        group
        for group in required_groups
        if not uploaded_files.getlist(group)
    ]

    if missing_groups:
        return api_response(
            {
                'error': 'missing_files',
                'message': '请上传当前表格类型所需的全部材料。',
                'missing_groups': missing_groups,
                'missing_group_labels': [FORM_ASSET_LABELS.get(group, group) for group in missing_groups],
            },
            status=400,
        )

    backend = form_automation_backend()
    if (
        backend != 'codex_worker'
        and not setting_or_env('OPENAI_API_KEY', '').strip()
        and not allow_form_review_fallback()
    ):
        return api_response(
            {
                'error': 'form_backend_not_ready',
                'message': (
                    '当前报销表格后端未启用 Codex Worker，也未配置 OPENAI_API_KEY。'
                    '为避免生成简易待复核表，本次提交已拒绝。'
                    '请启动 Codex Worker 或配置 OPENAI_API_KEY 后再提交。'
                ),
                'backend': backend,
            },
            status=503,
        )

    job = FormAutomationJob.objects.create(
        form_type=form_type,
        status=FormAutomationJob.Status.PENDING,
    )

    try:
        for group in ('purchase_screenshots', 'invoices', 'reference_images', 'link_txt'):
            for uploaded_file in uploaded_files.getlist(group):
                FormAutomationAsset.objects.create(
                    job=job,
                    group=group,
                    file=uploaded_file,
                    original_name=uploaded_file.name,
                    size=uploaded_file.size,
                )

        job.summary = {
            'mode': 'codex-skill-worker' if backend == 'codex_worker' else 'work05-compatible',
            'backend': backend,
            'message': (
                '任务已进入 Codex Worker 队列；Windows Worker 会使用 expense-procurement-forms skill 生成表格。'
                if backend == 'codex_worker'
                else '已进入 work05 兼容表格生成管线；若已配置 OpenAI API Key，将自动识别字段，否则生成待人工复核表。'
            ),
            'asset_counts': {
                group: job.assets.filter(group=group).count()
                for group in ('purchase_screenshots', 'invoices', 'reference_images', 'link_txt')
            },
        }
        if backend == 'codex_worker':
            job.status = FormAutomationJob.Status.PENDING
            job.progress = 0
            job.progress_message = '等待 Worker 处理'
            job.error_message = ''
            job.save(update_fields=['summary', 'status', 'progress', 'progress_message', 'error_message', 'updated_at'])
            return api_response(serialize_form_automation_job(job), status=201)

        job.status = FormAutomationJob.Status.RUNNING
        job.progress = 10
        job.progress_message = '正在生成表格'
        job.started_at = timezone.now()
        job.save(update_fields=['status', 'progress', 'progress_message', 'started_at', 'updated_at'])
        base_url = request.build_absolute_uri('/').rstrip('/')
        generate_form_automation_workbook(job, base_url=base_url)
        job.status = FormAutomationJob.Status.SUCCESS
        job.progress = 100
        job.progress_message = '处理成功'
        job.finished_at = timezone.now()
        job.error_message = ''
        job.save(
            update_fields=[
                'summary', 'result_file', 'status', 'progress', 'progress_message',
                'finished_at', 'error_message', 'updated_at',
            ]
        )
        return api_response(serialize_form_automation_job(job), status=201)
    except Exception as exc:
        job.status = FormAutomationJob.Status.FAILED
        job.progress_message = '处理失败'
        job.finished_at = timezone.now()
        job.error_message = str(exc)
        job.save(update_fields=['status', 'progress_message', 'finished_at', 'error_message', 'updated_at'])
        payload = serialize_form_automation_job(job)
        payload.update(
            {
                'error': 'form_generation_failed',
                'message': '上传成功，但表格生成失败。',
                'detail': str(exc) if settings.DEBUG else '',
            }
        )
        return api_response(payload, status=500)


@require_GET
def get_form_automation_job(_request, job_id):
    job = get_object_or_404(FormAutomationJob, id=job_id)
    return api_response(serialize_form_automation_job(job))


@require_GET
def download_form_automation_result(_request, job_id):
    job = get_object_or_404(FormAutomationJob, id=job_id)

    if job.status != FormAutomationJob.Status.SUCCESS or not job.result_file:
        raise Http404('Form automation result is not ready.')

    try:
        response = FileResponse(
            job.result_file.open('rb'),
            as_attachment=True,
            filename=form_automation_result_filename(job),
        )
    except FileNotFoundError as exc:
        raise Http404('Form automation result file was not found.') from exc

    return response


@csrf_exempt
@require_POST
def worker_next_form_automation_job(request):
    if not require_worker_token(request):
        return api_response(
            {
                'error': 'worker_unauthorized',
                'message': 'Worker token 未配置或不正确。',
            },
            status=403,
        )

    body = parse_json_body(request)
    job = claim_next_worker_job(FormAutomationJob, request_worker_id(request, body))
    if not job:
        return api_response({'ok': True, 'job': None})

    return api_response(worker_job_payload(request, job))


@csrf_exempt
@require_POST
def worker_heartbeat_form_automation_job(request, job_id):
    return update_worker_heartbeat(request, FormAutomationJob, serialize_form_automation_job, job_id)


@require_GET
def worker_download_form_automation_asset(request, asset_id):
    if not require_worker_token(request):
        return api_response(
            {
                'error': 'worker_unauthorized',
                'message': 'Worker token 未配置或不正确。',
            },
            status=403,
        )

    asset = get_object_or_404(FormAutomationAsset, id=asset_id)
    try:
        response = FileResponse(
            asset.file.open('rb'),
            as_attachment=True,
            filename=asset.original_name,
        )
    except FileNotFoundError as exc:
        raise Http404('Form automation asset file was not found.') from exc
    return response


@csrf_exempt
@require_POST
def worker_complete_form_automation_job(request, job_id):
    if not require_worker_token(request):
        return api_response(
            {
                'error': 'worker_unauthorized',
                'message': 'Worker token 未配置或不正确。',
            },
            status=403,
        )

    result_file = request.FILES.get('result_file')
    if not result_file:
        return api_response(
            {
                'error': 'missing_result_file',
                'message': '请上传 Worker 生成的 result_file。',
            },
            status=400,
        )

    claim_token = request_claim_token(request)
    with transaction.atomic():
        job = get_object_or_404(FormAutomationJob.objects.select_for_update(), id=job_id)
        if job.status == FormAutomationJob.Status.SUCCESS and job.result_file:
            return api_response(serialize_form_automation_job(job))
        if not worker_claim_matches(job, claim_token):
            return api_response(
                {'error': 'worker_claim_expired', 'message': '任务已被重新分配或已经结束，当前结果不会写入。'},
                status=409,
            )

        summary = dict(job.summary or {})
        raw_summary = request.POST.get('summary', '').strip()
        if raw_summary:
            try:
                worker_summary = json.loads(raw_summary)
                if isinstance(worker_summary, dict):
                    summary.update(worker_summary)
            except json.JSONDecodeError:
                summary['worker_summary_parse_error'] = raw_summary[:500]
        summary.update(
            {
                'mode': 'codex-skill-worker',
                'backend': 'codex_worker',
                'worker_completed_at': timezone.localtime(timezone.now()).isoformat(),
                'result_filename': result_file.name,
            }
        )

        job.result_file.save(result_file.name, result_file, save=False)
        job.summary = summary
        job.status = FormAutomationJob.Status.SUCCESS
        job.progress = 100
        job.progress_message = '处理成功'
        job.claim_token = None
        job.lease_expires_at = None
        job.finished_at = timezone.now()
        job.error_message = ''
        job.save(
            update_fields=[
                'summary', 'result_file', 'status', 'progress', 'progress_message',
                'claim_token', 'lease_expires_at', 'finished_at', 'error_message', 'updated_at',
            ]
        )
    return api_response(serialize_form_automation_job(job))


@csrf_exempt
@require_POST
def worker_fail_form_automation_job(request, job_id):
    if not require_worker_token(request):
        return api_response(
            {
                'error': 'worker_unauthorized',
                'message': 'Worker token 未配置或不正确。',
            },
            status=403,
        )

    body = parse_json_body(request)
    error_message = (
        request.POST.get('error_message')
        or body.get('error_message')
        or 'Codex Worker 生成失败。'
    )
    claim_token = request_claim_token(request, body)
    with transaction.atomic():
        job = get_object_or_404(FormAutomationJob.objects.select_for_update(), id=job_id)
        if job.status in {FormAutomationJob.Status.SUCCESS, FormAutomationJob.Status.FAILED}:
            return api_response(serialize_form_automation_job(job))
        if not worker_claim_matches(job, claim_token):
            return api_response(
                {'error': 'worker_claim_expired', 'message': '任务已被重新分配或已经结束，当前失败信息不会写入。'},
                status=409,
            )

        summary = dict(job.summary or {})
        raw_summary = request.POST.get('summary') or body.get('summary')
        if isinstance(raw_summary, dict):
            summary.update(raw_summary)
        elif isinstance(raw_summary, str) and raw_summary.strip():
            try:
                parsed_summary = json.loads(raw_summary)
                if isinstance(parsed_summary, dict):
                    summary.update(parsed_summary)
            except json.JSONDecodeError:
                summary['worker_summary_parse_error'] = raw_summary[:500]
        summary.update(
            {
                'mode': 'codex-skill-worker',
                'backend': 'codex_worker',
                'worker_failed_at': timezone.localtime(timezone.now()).isoformat(),
            }
        )

        job.summary = summary
        job.status = FormAutomationJob.Status.FAILED
        job.progress_message = '处理失败'
        job.claim_token = None
        job.lease_expires_at = None
        job.finished_at = timezone.now()
        job.error_message = str(error_message)[:5000]
        job.save(
            update_fields=[
                'summary', 'status', 'progress_message', 'claim_token', 'lease_expires_at',
                'finished_at', 'error_message', 'updated_at',
            ]
        )
    return api_response(serialize_form_automation_job(job))
