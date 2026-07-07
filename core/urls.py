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
]
