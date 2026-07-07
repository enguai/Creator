from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import PayrollJob
from .payroll import FILE_LABELS, generate_placeholder_payroll


def serialize_payroll_job(job, request=None):
    download_url = ''
    if job.status == PayrollJob.Status.SUCCESS and job.result_file:
        download_url = reverse('payroll-job-download', args=[job.id])
        if request is not None:
            download_url = request.build_absolute_uri(download_url)

    return {
        'id': str(job.id),
        'room_type': job.room_type,
        'week_start': job.week_start.isoformat() if job.week_start else '',
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


@csrf_exempt
@require_POST
def create_payroll_job(request):
    required_files = [field_name for field_name, _label in FILE_LABELS]
    missing_files = [field_name for field_name in required_files if field_name not in request.FILES]

    if missing_files:
        return JsonResponse(
            {
                'error': 'missing_files',
                'message': '请上传全部四个薪资计算文件。',
                'missing_files': missing_files,
            },
            status=400,
        )

    week_start = None
    week_start_raw = request.POST.get('week_start', '').strip()
    if week_start_raw:
        week_start = parse_date(week_start_raw)
        if week_start is None:
            return JsonResponse(
                {
                    'error': 'invalid_week_start',
                    'message': '薪资周开始日期格式不正确，请使用 YYYY-MM-DD。',
                },
                status=400,
            )

    job = PayrollJob.objects.create(
        room_type=request.POST.get('room_type', 'general').strip() or 'general',
        week_start=week_start,
        host_schedule=request.FILES['host_schedule'],
        controller_schedule=request.FILES['controller_schedule'],
        trial_schedule=request.FILES['trial_schedule'],
        host_data=request.FILES['host_data'],
        status=PayrollJob.Status.RUNNING,
    )

    try:
        generate_placeholder_payroll(job)
        job.status = PayrollJob.Status.SUCCESS
        job.error_message = ''
        job.save(update_fields=['result_file', 'status', 'error_message', 'updated_at'])
        return JsonResponse(serialize_payroll_job(job, request), status=201)
    except Exception as exc:
        job.status = PayrollJob.Status.FAILED
        job.error_message = str(exc)
        job.save(update_fields=['status', 'error_message', 'updated_at'])
        return JsonResponse(serialize_payroll_job(job, request), status=500)


@require_GET
def get_payroll_job(request, job_id):
    job = get_object_or_404(PayrollJob, id=job_id)
    return JsonResponse(serialize_payroll_job(job, request))


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
