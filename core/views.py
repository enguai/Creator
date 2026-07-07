from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import PayrollJob
from .payroll import FILE_LABELS, generate_placeholder_payroll


def api_response(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={'ensure_ascii': False})


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
