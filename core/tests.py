import json
import re
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import unquote

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .douyin_monitor import matches_rule, parse_compact_number, validate_config
from .models import DouyinMonitorSession, FormAutomationJob, PayrollJob, Profile, UserSecurityEvent
from .views import serialize_form_automation_job


class WorkerQueueTests(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_dir.name,
            FORM_AUTOMATION_WORKER_TOKEN='test-worker-token',
            FORM_AUTOMATION_BACKEND='codex_worker',
            AUTOMATION_WORKER_LEASE_SECONDS=60,
            AUTOMATION_WORKER_MAX_ATTEMPTS=2,
        )
        self.settings_override.enable()
        self.user = User.objects.create_user('worker-test-user', 'worker@example.com', 'StrongPass123!')
        self.client.force_login(self.user)
        self.worker_headers = {'HTTP_X_CREATOR_WORKER_TOKEN': 'test-worker-token'}

    def tearDown(self):
        self.settings_override.disable()
        self.media_dir.cleanup()

    def post_json(self, url, payload=None):
        return self.client.post(
            url,
            data=json.dumps(payload or {}),
            content_type='application/json',
            **self.worker_headers,
        )

    def create_form_job(self, **overrides):
        values = {
            'form_type': FormAutomationJob.FormType.EXPENSE,
            'status': FormAutomationJob.Status.PENDING,
        }
        values.update(overrides)
        return FormAutomationJob.objects.create(owner=self.user, **values)

    def create_payroll_job(self):
        return PayrollJob.objects.create(
            owner=self.user,
            room_type='z3-polish',
            status=PayrollJob.Status.PENDING,
            host_schedule=SimpleUploadedFile('host.xlsx', b'host'),
            controller_schedule=SimpleUploadedFile('controller.xlsx', b'controller'),
            trial_schedule=SimpleUploadedFile('trial.xlsx', b'trial'),
            host_data=SimpleUploadedFile('data.xlsx', b'data'),
        )

    def test_form_job_is_claimed_only_once(self):
        job = self.create_form_job()
        url = reverse('form-automation-worker-job-next')

        first = self.post_json(url, {'worker_id': 'worker-a'})
        second = self.post_json(url, {'worker_id': 'worker-b'})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['job']['id'], str(job.id))
        self.assertTrue(first.json()['claim_token'])
        self.assertIsNone(second.json()['job'])
        job.refresh_from_db()
        self.assertEqual(job.status, FormAutomationJob.Status.RUNNING)
        self.assertEqual(job.progress, 5)
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.worker_id, 'worker-a')

    def test_heartbeat_updates_progress_and_rejects_wrong_claim(self):
        job = self.create_form_job()
        claimed = self.post_json(
            reverse('form-automation-worker-job-next'),
            {'worker_id': 'worker-a'},
        ).json()
        heartbeat_url = reverse('form-automation-worker-job-heartbeat', args=[job.id])

        rejected = self.post_json(
            heartbeat_url,
            {'claim_token': str(uuid.uuid4()), 'progress': 80, 'message': '错误 Worker'},
        )
        accepted = self.post_json(
            heartbeat_url,
            {'claim_token': claimed['claim_token'], 'progress': 42, 'message': '正在生成表格'},
        )

        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(accepted.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.progress, 42)
        self.assertEqual(job.progress_message, '正在生成表格')
        self.assertGreater(job.lease_expires_at, timezone.now())

    def test_stale_job_is_retried_with_a_new_claim(self):
        old_claim = uuid.uuid4()
        job = self.create_form_job(
            status=FormAutomationJob.Status.RUNNING,
            progress=60,
            progress_message='旧 Worker 正在处理',
            worker_id='old-worker',
            claim_token=old_claim,
            lease_expires_at=timezone.now() - timedelta(minutes=5),
            attempt_count=1,
        )

        response = self.post_json(
            reverse('form-automation-worker-job-next'),
            {'worker_id': 'new-worker'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['job']['id'], str(job.id))
        self.assertNotEqual(response.json()['claim_token'], str(old_claim))
        job.refresh_from_db()
        self.assertEqual(job.status, FormAutomationJob.Status.RUNNING)
        self.assertEqual(job.attempt_count, 2)
        self.assertEqual(job.worker_id, 'new-worker')

    def test_stale_job_fails_after_maximum_attempts(self):
        job = self.create_form_job(
            status=FormAutomationJob.Status.RUNNING,
            claim_token=uuid.uuid4(),
            lease_expires_at=timezone.now() - timedelta(minutes=5),
            attempt_count=2,
        )

        response = self.post_json(reverse('form-automation-worker-job-next'))

        self.assertIsNone(response.json()['job'])
        job.refresh_from_db()
        self.assertEqual(job.status, FormAutomationJob.Status.FAILED)
        self.assertIn('最大重试次数', job.error_message)
        self.assertIsNotNone(job.finished_at)

    def test_only_current_claim_can_complete_job(self):
        job = self.create_form_job()
        claimed = self.post_json(reverse('form-automation-worker-job-next')).json()
        url = reverse('form-automation-worker-job-complete', args=[job.id])

        rejected = self.client.post(
            url,
            data={
                'claim_token': str(uuid.uuid4()),
                'result_file': SimpleUploadedFile('result.xlsx', b'wrong'),
            },
            **self.worker_headers,
        )
        accepted = self.client.post(
            url,
            data={
                'claim_token': claimed['claim_token'],
                'result_file': SimpleUploadedFile('result.xlsx', b'correct'),
            },
            **self.worker_headers,
        )

        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(accepted.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, FormAutomationJob.Status.SUCCESS)
        self.assertEqual(job.progress, 100)
        self.assertEqual(job.progress_message, '处理成功')
        self.assertIsNone(job.claim_token)

        download = self.client.get(reverse('form-automation-job-download', args=[job.id]))
        self.assertEqual(download.status_code, 200)
        self.assertIn('费用报销表', unquote(download.headers['Content-Disposition']))
        download.close()

    def test_unified_task_query_supports_payroll_jobs(self):
        job = self.create_payroll_job()
        claimed = self.post_json(
            reverse('payroll-worker-job-next'),
            {'worker_id': 'payroll-worker'},
        )
        self.assertEqual(claimed.status_code, 200)

        response = self.client.get(reverse('worker-task-detail', args=[job.id]))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['task_type'], 'payroll')
        self.assertEqual(payload['outcome'], 'processing')
        self.assertEqual(payload['progress'], 5)
        self.assertEqual(payload['attempt_count'], 1)
        self.assertEqual(len(payload['files']), 4)

    def test_unified_task_query_uses_the_same_processing_duration_as_job_payload(self):
        started_at = timezone.now() - timedelta(seconds=65)
        job = self.create_form_job(
            status=FormAutomationJob.Status.RUNNING,
            started_at=started_at,
            progress=35,
        )

        response = self.client.get(reverse('worker-task-detail', args=[job.id]))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['processing_duration_seconds'], serialize_form_automation_job(job)['processing_duration_seconds'])
        self.assertGreaterEqual(payload['processing_duration_seconds'], 65)
        self.assertLess(payload['processing_duration_seconds'], 70)

    @override_settings(CREATOR_CLOUD_SERVER_URL='http://cloud.example')
    @patch('core.views.get_cloud_worker_task')
    def test_unified_task_query_falls_back_to_cloud(self, get_cloud_worker_task):
        job_id = uuid.uuid4()
        get_cloud_worker_task.return_value = {
            'id': str(job_id),
            'status': 'success',
            'progress': 100,
            'download_url': 'http://cloud.example/api/forms/result/download/',
            'task_source': 'cloud',
        }

        response = self.client.get(reverse('worker-task-detail', args=[job_id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['id'], str(job_id))
        self.assertEqual(response.json()['task_source'], 'cloud')
        get_cloud_worker_task.assert_called_once()


class DouyinMonitorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('monitor-test-user', 'monitor@example.com', 'StrongPass123!')
        self.client.force_login(self.user)

    def test_rule_validation_and_compact_counts_match_desktop_app(self):
        self.assertTrue(matches_rule(101, {'mode': 'greater', 'threshold': 100}))
        self.assertFalse(matches_rule(100, {'mode': 'greater', 'threshold': 100}))
        self.assertEqual(parse_compact_number('1.2万'), 12000)
        self.assertEqual(parse_compact_number('1,234'), 1234)
        self.assertFalse(validate_config({'enabled': True, 'webhook': 'http://example.com'})[0])
        self.assertFalse(validate_config({'mode': 'range', 'min': 10, 'max': 5})[0])

    def test_empty_monitor_input_is_rejected_without_creating_a_session(self):
        response = self.client.post(
            reverse('douyin-monitor-start'),
            data=json.dumps({'douyinId': ''}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])
        self.assertEqual(DouyinMonitorSession.objects.count(), 0)

    def test_config_export_and_log_deletion(self):
        self.client.get(reverse('douyin-monitor-state'))
        session = DouyinMonitorSession.objects.create(
            owner=self.user,
            douyin_id='creator-test',
            room_title='测试直播间',
            status=DouyinMonitorSession.Status.MONITORING,
            current_count=88,
            points=[{'time': 1000, 'count': 88}],
            alerts=[{'time': 2000, 'count': 76, 'status': 'sent'}],
        )
        config_response = self.client.put(
            reverse('douyin-monitor-config', args=[session.id]),
            data=json.dumps({
                'enabled': False,
                'mode': 'range',
                'min': 50,
                'max': 100,
                'cooldownEnabled': True,
                'cooldownMinutes': 15,
            }),
            content_type='application/json',
        )
        self.assertEqual(config_response.status_code, 200)
        self.assertEqual(config_response.json()['monitor']['config']['mode'], 'range')

        export_response = self.client.get(reverse('douyin-monitor-log-export', args=[session.id]))
        self.assertEqual(export_response.status_code, 200)
        report_html = export_response.content.decode('utf-8')
        self.assertIn('每15分钟', report_html)
        self.assertIn('告警时间点', report_html)
        self.assertIn('时间点在线人数', report_html)
        self.assertIn('<details class="alert-history">', report_html)
        self.assertIn('收起明细', report_html)
        self.assertIn('"count": 76', report_html)

        self.client.post(reverse('douyin-monitor-stop', args=[session.id]))
        delete_response = self.client.delete(reverse('douyin-monitor-log-delete', args=[session.id]))
        self.assertEqual(delete_response.status_code, 200)
        self.assertFalse(DouyinMonitorSession.objects.filter(id=session.id).exists())


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class AuthenticationTests(TestCase):
    def test_anonymous_user_cannot_access_tools_api(self):
        response = self.client.get(reverse('worker-task-recent'))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'authentication_required')

    def test_health_checks_remain_public(self):
        self.assertEqual(self.client.get(reverse('form-automation-health')).status_code, 200)
        self.assertEqual(self.client.get(reverse('payroll-health')).status_code, 200)

    def test_registration_creates_session_and_security_events(self):
        response = self.client.post(
            reverse('auth-register'),
            data=json.dumps({
                'username': 'creator-user',
                'email': 'creator@example.com',
                'password1': 'StrongPass123!',
                'password2': 'StrongPass123!',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()['authenticated'])
        self.assertEqual(response.json()['user']['username'], 'creator-user')
        self.assertEqual(User.objects.get(username='creator-user').profile.nickname, 'creator-user')
        self.assertTrue(UserSecurityEvent.objects.filter(event=UserSecurityEvent.Event.REGISTERED).exists())

    def test_password_reset_with_email_code_changes_password(self):
        user = User.objects.create_user('reset-user', 'reset@example.com', 'OldStrongPass123!')
        Profile.objects.create(user=user, nickname=user.username)
        request_response = self.client.post(
            reverse('auth-verification-code'),
            data=json.dumps({
                'channel': 'email',
                'purpose': 'password_reset',
                'destination': user.email,
            }),
            content_type='application/json',
        )

        self.assertEqual(request_response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        code = re.search(r'\b\d{6}\b', mail.outbox[0].body).group(0)
        confirm_response = self.client.post(
            reverse('auth-password-reset-confirm'),
            data=json.dumps({
                'email': user.email,
                'code': code,
                'password1': 'NewStrongPass123!',
                'password2': 'NewStrongPass123!',
            }),
            content_type='application/json',
        )

        self.assertEqual(confirm_response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('NewStrongPass123!'))

    def test_phone_code_login_is_not_supported(self):
        code_response = self.client.post(
            reverse('auth-verification-code'),
            data=json.dumps({
                'channel': 'sms',
                'purpose': 'phone_login',
                'destination': '13800138002',
            }),
            content_type='application/json',
        )

        self.assertEqual(code_response.status_code, 400)
        login_response = self.client.post(
            reverse('auth-login'),
            data=json.dumps({
                'method': 'sms',
                'phone': '13800138002',
                'code': '123456',
            }),
            content_type='application/json',
        )

        self.assertEqual(login_response.status_code, 400)
        self.assertEqual(login_response.json()['message'], '只支持用户名和密码登录。')

    def test_account_recovery_requires_email_code(self):
        user = User.objects.create_user('recover-user', 'recover@example.com', 'StrongPass123!')
        Profile.objects.create(user=user, nickname=user.username)
        code_response = self.client.post(
            reverse('auth-verification-code'),
            data=json.dumps({
                'channel': 'email',
                'purpose': 'account_recovery',
                'destination': user.email,
            }),
            content_type='application/json',
        )
        self.assertEqual(code_response.status_code, 200)
        code = re.search(r'\b\d{6}\b', mail.outbox[0].body).group(0)

        recovery_response = self.client.post(
            reverse('auth-recover-account'),
            data=json.dumps({'email': user.email, 'code': code}),
            content_type='application/json',
        )

        self.assertEqual(recovery_response.status_code, 200)
        self.assertEqual(recovery_response.json()['usernames'], [user.username])

    def test_user_cannot_read_another_users_task(self):
        owner = User.objects.create_user('task-owner', 'owner@example.com', 'StrongPass123!')
        stranger = User.objects.create_user('task-stranger', 'stranger@example.com', 'StrongPass123!')
        job = FormAutomationJob.objects.create(owner=owner, form_type=FormAutomationJob.FormType.EXPENSE)
        self.client.force_login(stranger)

        response = self.client.get(reverse('form-automation-job-detail', args=[job.id]))

        self.assertEqual(response.status_code, 404)

    def test_recent_tasks_prefers_active_task_for_each_user(self):
        user = User.objects.create_user('recent-owner', 'recent@example.com', 'StrongPass123!')
        FormAutomationJob.objects.create(
            owner=user,
            form_type=FormAutomationJob.FormType.EXPENSE,
            status=FormAutomationJob.Status.SUCCESS,
        )
        active_job = FormAutomationJob.objects.create(
            owner=user,
            form_type=FormAutomationJob.FormType.PROCUREMENT,
            status=FormAutomationJob.Status.RUNNING,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('worker-task-recent'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['tasks'][0]['id'], str(active_job.id))

    def test_login_is_temporarily_blocked_after_repeated_failures(self):
        User.objects.create_user('limited-user', 'limited@example.com', 'StrongPass123!')
        url = reverse('auth-login')
        for _index in range(5):
            response = self.client.post(
                url,
                data=json.dumps({'username': 'limited-user', 'password': 'wrong'}),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 401)

        blocked = self.client.post(
            url,
            data=json.dumps({'username': 'limited-user', 'password': 'StrongPass123!'}),
            content_type='application/json',
        )

        self.assertEqual(blocked.status_code, 429)


class AdminUserManagementTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            username='admin-user',
            email='admin@example.com',
            password='StrongAdminPass123!',
        )
        Profile.objects.create(user=self.admin_user, nickname=self.admin_user.username)
        self.client.force_login(self.admin_user)

    def test_user_list_is_the_only_user_profile_management_page(self):
        response = self.client.get(reverse('admin:auth_user_changelist'))

        self.assertEqual(response.status_code, 200)
        headings = (
            '\u7528\u6237\u540d',
            '\u90ae\u7bb1',
            '\u5bc6\u7801',
            '\u662f\u5426\u6fc0\u6d3b',
            '\u6ce8\u518c\u65e5\u671f',
            '\u6700\u8fd1\u767b\u5f55',
        )
        for heading in headings:
            self.assertContains(response, heading)
        self.assertNotIn('phone_number', admin.site._registry[User].list_display)
        self.assertFalse(admin.site.is_registered(Profile))

    def test_admin_can_create_user_profile_together(self):
        response = self.client.post(
            reverse('admin:auth_user_add'),
            data={
                'username': 'created-in-admin',
                'email': 'created-in-admin@example.com',
                'password1': 'StrongCreatedPass123!',
                'password2': 'StrongCreatedPass123!',
                'is_active': 'on',
                '_save': '1',
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='created-in-admin')
        self.assertEqual(user.profile.nickname, user.username)
        self.assertTrue(user.is_active)
