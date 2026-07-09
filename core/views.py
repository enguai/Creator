import hmac
import json
import os

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .form_automation import FORM_ASSET_LABELS, form_automation_capabilities, generate_form_automation_workbook
from .models import FormAutomationAsset, FormAutomationJob, PayrollJob
from .payroll import FILE_LABELS, generate_placeholder_payroll


def api_response(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


def setting_or_env(name, default=''):
    return getattr(settings, name, None) or os.environ.get(name, default)


def form_automation_backend():
    return setting_or_env('FORM_AUTOMATION_BACKEND', 'sync').strip().lower() or 'sync'


def worker_token():
    return setting_or_env('FORM_AUTOMATION_WORKER_TOKEN', '').strip()


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
        'created_at': job.created_at.isoformat(),
        'updated_at': job.updated_at.isoformat(),
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


@require_GET
def payroll_health(_request):
    return api_response(
        {
            'ok': True,
            'service': 'creator-payroll',
            'message': '薪资计算后端已连接。',
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

    try:
        job = PayrollJob.objects.create(
            room_type=post_data.get('room_type', 'general').strip() or 'general',
            week_start=week_start,
            week_end=week_end,
            host_schedule=uploaded_files['host_schedule'],
            controller_schedule=uploaded_files['controller_schedule'],
            trial_schedule=uploaded_files['trial_schedule'],
            host_data=uploaded_files['host_data'],
            status=PayrollJob.Status.RUNNING,
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

    try:
        generate_placeholder_payroll(job)
        job.status = PayrollJob.Status.SUCCESS
        job.error_message = ''
        job.save(update_fields=['result_file', 'status', 'error_message', 'updated_at'])
        return api_response(serialize_payroll_job(job), status=201)
    except Exception as exc:
        job.status = PayrollJob.Status.FAILED
        job.error_message = str(exc)
        job.save(update_fields=['status', 'error_message', 'updated_at'])
        payload = serialize_payroll_job(job)
        payload.update(
            {
                'error': 'placeholder_generation_failed',
                'message': '上传成功，但测试薪资文档生成失败。',
                'detail': str(exc) if settings.DEBUG else '',
            }
        )
        return api_response(payload, status=500)


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

        backend = form_automation_backend()
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
            job.error_message = ''
            job.save(update_fields=['summary', 'status', 'error_message', 'updated_at'])
            return api_response(serialize_form_automation_job(job), status=201)

        job.status = FormAutomationJob.Status.RUNNING
        base_url = request.build_absolute_uri('/').rstrip('/')
        generate_form_automation_workbook(job, base_url=base_url)
        job.status = FormAutomationJob.Status.SUCCESS
        job.error_message = ''
        job.save(update_fields=['summary', 'result_file', 'status', 'error_message', 'updated_at'])
        return api_response(serialize_form_automation_job(job), status=201)
    except Exception as exc:
        job.status = FormAutomationJob.Status.FAILED
        job.error_message = str(exc)
        job.save(update_fields=['status', 'error_message', 'updated_at'])
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
            filename=job.result_file.name.split('/')[-1],
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

    with transaction.atomic():
        job = (
            FormAutomationJob.objects.select_for_update()
            .filter(status=FormAutomationJob.Status.PENDING)
            .order_by('created_at')
            .first()
        )
        if not job:
            return api_response({'ok': True, 'job': None})

        summary = dict(job.summary or {})
        summary.update(
            {
                'mode': 'codex-skill-worker',
                'backend': 'codex_worker',
                'worker_claimed_at': timezone.localtime(timezone.now()).isoformat(),
            }
        )
        job.summary = summary
        job.status = FormAutomationJob.Status.RUNNING
        job.error_message = ''
        job.save(update_fields=['summary', 'status', 'error_message', 'updated_at'])

    return api_response(worker_job_payload(request, job))


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

    job = get_object_or_404(FormAutomationJob, id=job_id)
    result_file = request.FILES.get('result_file')
    if not result_file:
        return api_response(
            {
                'error': 'missing_result_file',
                'message': '请上传 Worker 生成的 result_file。',
            },
            status=400,
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
    job.error_message = ''
    job.save(update_fields=['summary', 'result_file', 'status', 'error_message', 'updated_at'])
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

    job = get_object_or_404(FormAutomationJob, id=job_id)
    body = parse_json_body(request)
    error_message = (
        request.POST.get('error_message')
        or body.get('error_message')
        or 'Codex Worker 生成失败。'
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
    job.error_message = str(error_message)[:5000]
    job.save(update_fields=['summary', 'status', 'error_message', 'updated_at'])
    return api_response(serialize_form_automation_job(job))
