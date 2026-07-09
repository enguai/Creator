from django.urls import path

from . import views


urlpatterns = [
    path('payroll/health/', views.payroll_health, name='payroll-health'),
    path('payroll/jobs/', views.create_payroll_job, name='payroll-job-create'),
    path('payroll/jobs/<uuid:job_id>/', views.get_payroll_job, name='payroll-job-detail'),
    path(
        'payroll/jobs/<uuid:job_id>/download/',
        views.download_payroll_result,
        name='payroll-job-download',
    ),
    path('forms/health/', views.form_automation_health, name='form-automation-health'),
    path('forms/jobs/', views.create_form_automation_job, name='form-automation-job-create'),
    path('forms/jobs/<uuid:job_id>/', views.get_form_automation_job, name='form-automation-job-detail'),
    path(
        'forms/jobs/<uuid:job_id>/download/',
        views.download_form_automation_result,
        name='form-automation-job-download',
    ),
    path(
        'forms/worker/jobs/next/',
        views.worker_next_form_automation_job,
        name='form-automation-worker-job-next',
    ),
    path(
        'forms/worker/assets/<int:asset_id>/download/',
        views.worker_download_form_automation_asset,
        name='form-automation-worker-asset-download',
    ),
    path(
        'forms/worker/jobs/<uuid:job_id>/complete/',
        views.worker_complete_form_automation_job,
        name='form-automation-worker-job-complete',
    ),
    path(
        'forms/worker/jobs/<uuid:job_id>/fail/',
        views.worker_fail_form_automation_job,
        name='form-automation-worker-job-fail',
    ),
]
