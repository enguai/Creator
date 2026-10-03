from django.urls import path

from . import views
from . import douyin_views
from . import auth_views
from . import guard_license_views
from . import knowledge_views


urlpatterns = [
    path('knowledge/catalog/', knowledge_views.knowledge_catalog, name='knowledge-catalog'),
    path('knowledge/articles/', knowledge_views.knowledge_list, name='knowledge-list'),
    path('knowledge/articles/<uuid:article_id>/', knowledge_views.knowledge_detail, name='knowledge-detail'),
    path('knowledge/questions/', knowledge_views.create_knowledge_question, name='knowledge-question-create'),
    path('knowledge/questions/<uuid:job_id>/', knowledge_views.get_knowledge_question, name='knowledge-question-detail'),
    path('knowledge/questions/<uuid:job_id>/download/', knowledge_views.download_knowledge_question_result, name='knowledge-question-download'),
    path('knowledge/conversations/', knowledge_views.knowledge_conversation_list, name='knowledge-conversation-list'),
    path('knowledge/conversations/<uuid:conversation_id>/', knowledge_views.knowledge_conversation_detail, name='knowledge-conversation-detail'),
    path('knowledge/worker/jobs/next/', knowledge_views.worker_next_knowledge_question, name='knowledge-worker-job-next'),
    path('knowledge/worker/jobs/<uuid:job_id>/heartbeat/', knowledge_views.worker_heartbeat_knowledge_question, name='knowledge-worker-job-heartbeat'),
    path('knowledge/worker/assets/<int:asset_id>/download/', knowledge_views.worker_download_knowledge_asset, name='knowledge-worker-asset-download'),
    path('knowledge/worker/jobs/<uuid:job_id>/complete/', knowledge_views.worker_complete_knowledge_question, name='knowledge-worker-job-complete'),
    path('knowledge/worker/jobs/<uuid:job_id>/fail/', knowledge_views.worker_fail_knowledge_question, name='knowledge-worker-job-fail'),
    path('guard-license/activate/', guard_license_views.activate_license, name='guard-license-activate'),
    path('guard-license/validate/', guard_license_views.validate_license, name='guard-license-validate'),
    path('auth/session/', auth_views.session_detail, name='auth-session'),
    path('auth/login/', auth_views.login_user, name='auth-login'),
    path('auth/logout/', auth_views.logout_user, name='auth-logout'),
    path('auth/register/', auth_views.register_user, name='auth-register'),
    path('auth/verification-code/', auth_views.send_verification_code, name='auth-verification-code'),
    path('auth/recover-account/', auth_views.recover_account, name='auth-recover-account'),
    path('auth/password-reset/', auth_views.request_password_reset, name='auth-password-reset'),
    path(
        'auth/password-reset-confirm/',
        auth_views.confirm_password_reset,
        name='auth-password-reset-confirm',
    ),
    path('live-monitor/health/', douyin_views.monitor_health, name='douyin-monitor-health'),
    path('live-monitor/state/', douyin_views.monitor_state, name='douyin-monitor-state'),
    path('live-monitor/monitors/', douyin_views.start_monitor, name='douyin-monitor-start'),
    path('live-monitor/monitors/<uuid:session_id>/stop/', douyin_views.stop_monitor, name='douyin-monitor-stop'),
    path(
        'live-monitor/monitors/<uuid:session_id>/refresh-stream/',
        douyin_views.refresh_monitor_stream,
        name='douyin-monitor-refresh-stream',
    ),
    path(
        'live-monitor/monitors/<uuid:session_id>/config/',
        douyin_views.save_monitor_config,
        name='douyin-monitor-config',
    ),
    path(
        'live-monitor/monitors/<uuid:session_id>/stream/',
        douyin_views.monitor_stream,
        name='douyin-monitor-stream',
    ),
    path(
        'live-monitor/logs/<uuid:session_id>/export/',
        douyin_views.export_monitor_log,
        name='douyin-monitor-log-export',
    ),
    path(
        'live-monitor/logs/<uuid:session_id>/',
        douyin_views.delete_monitor_log,
        name='douyin-monitor-log-delete',
    ),
    path('tasks/recent/', views.get_recent_worker_tasks, name='worker-task-recent'),
    path('tasks/<uuid:job_id>/', views.get_worker_task, name='worker-task-detail'),
    path('payroll/health/', views.payroll_health, name='payroll-health'),
    path('payroll/jobs/', views.create_payroll_job, name='payroll-job-create'),
    path('payroll/jobs/<uuid:job_id>/', views.get_payroll_job, name='payroll-job-detail'),
    path(
        'payroll/jobs/<uuid:job_id>/download/',
        views.download_payroll_result,
        name='payroll-job-download',
    ),
    path(
        'payroll/worker/jobs/next/',
        views.worker_next_payroll_job,
        name='payroll-worker-job-next',
    ),
    path(
        'payroll/worker/jobs/<uuid:job_id>/assets/<str:field_name>/download/',
        views.worker_download_payroll_asset,
        name='payroll-worker-asset-download',
    ),
    path(
        'payroll/worker/jobs/<uuid:job_id>/complete/',
        views.worker_complete_payroll_job,
        name='payroll-worker-job-complete',
    ),
    path(
        'payroll/worker/jobs/<uuid:job_id>/heartbeat/',
        views.worker_heartbeat_payroll_job,
        name='payroll-worker-job-heartbeat',
    ),
    path(
        'payroll/worker/jobs/<uuid:job_id>/fail/',
        views.worker_fail_payroll_job,
        name='payroll-worker-job-fail',
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
        'forms/worker/jobs/<uuid:job_id>/heartbeat/',
        views.worker_heartbeat_form_automation_job,
        name='form-automation-worker-job-heartbeat',
    ),
    path(
        'forms/worker/jobs/<uuid:job_id>/fail/',
        views.worker_fail_form_automation_job,
        name='form-automation-worker-job-fail',
    ),
]
