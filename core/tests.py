import json
import re
import tempfile
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .douyin_monitor import matches_rule, monitor_manager, parse_compact_number, validate_config
from .form_automation import match_invoice_for_group
from .models import (
    DouyinMonitorSession,
    FormAutomationJob,
    GuardLicense,
    GuardLicenseDevice,
    PayrollJob,
    Profile,
    UserSecurityEvent,
)
from .knowledge_models import KnowledgeQuestionJob
from .views import serialize_form_automation_job, serialize_payroll_job


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
            schedule_image=SimpleUploadedFile('schedule.png', b'schedule', content_type='image/png'),
            host_data=SimpleUploadedFile('data.xlsx', b'data'),
            rating_update=SimpleUploadedFile('rating.png', b'rating', content_type='image/png'),
        )

    def test_knowledge_question_accepts_multiple_data_source_files(self):
        response = self.client.post(
            reverse('knowledge-question-create'),
            {
                'question': '请分析这两份数据。',
                'files': [
                    SimpleUploadedFile('sales.xlsx', b'xlsx-data', content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    SimpleUploadedFile('notes.pdf', b'pdf-data', content_type='application/pdf'),
                ],
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(len(payload['files']), 2)
        job = KnowledgeQuestionJob.objects.get(id=payload['id'])
        self.assertEqual(job.assets.count(), 2)
        self.assertEqual(
            set(job.assets.values_list('original_name', flat=True)),
            {'sales.xlsx', 'notes.pdf'},
        )

    def test_knowledge_question_rejects_unsupported_file(self):
        response = self.client.post(
            reverse('knowledge-question-create'),
            {
                'question': '请分析文件。',
                'files': [SimpleUploadedFile('script.exe', b'not-allowed')],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('不支持', response.json()['message'])
        self.assertEqual(KnowledgeQuestionJob.objects.count(), 0)

    def test_knowledge_worker_payload_contains_and_protects_uploaded_files(self):
        created = self.client.post(
            reverse('knowledge-question-create'),
            {
                'question': '请读取这份表格。',
                'files': [SimpleUploadedFile('data.csv', b'a,b\n1,2', content_type='text/csv')],
            },
        )
        job_id = created.json()['id']

        claimed = self.post_json(
            reverse('knowledge-worker-job-next'),
            {'worker_id': 'worker-a'},
        )
        self.assertEqual(claimed.status_code, 200)
        asset = claimed.json()['assets'][0]
        self.assertEqual(asset['name'], 'data.csv')

        denied = self.client.get(reverse('knowledge-worker-asset-download', args=[asset['id']]))
        self.assertEqual(denied.status_code, 403)
        downloaded = self.client.get(
            reverse('knowledge-worker-asset-download', args=[asset['id']]),
            **self.worker_headers,
        )
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(b''.join(downloaded.streaming_content), b'a,b\n1,2')
        self.assertEqual(claimed.json()['job']['id'], job_id)

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
        self.assertEqual(len(payload['files']), 3)

    def test_payroll_submission_accepts_two_required_files_and_optional_rating_update(self):
        response = self.client.post(
            reverse('payroll-job-create'),
            data={
                'room_type': 'z2-eye',
                'schedule_image': SimpleUploadedFile('schedule.png', b'schedule', content_type='image/png'),
                'host_data': SimpleUploadedFile('host-data.xlsx', b'data'),
                'rating_update': SimpleUploadedFile('ratings.png', b'ratings', content_type='image/png'),
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual([item['field'] for item in payload['files']], [
            'schedule_image',
            'host_data',
            'rating_update',
        ])
        job = PayrollJob.objects.get(id=payload['id'])
        self.assertFalse(job.host_schedule)
        self.assertTrue(job.summary['rating_update_supplied'])

    def test_payroll_submission_accepts_no_rating_update(self):
        response = self.client.post(
            reverse('payroll-job-create'),
            data={
                'room_type': 'z4-neck',
                'schedule_image': SimpleUploadedFile('schedule.jpg', b'schedule', content_type='image/jpeg'),
                'host_data': SimpleUploadedFile('host-data.xlsx', b'data'),
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            [item['field'] for item in response.json()['files']],
            ['schedule_image', 'host_data'],
        )

    def test_z5_payroll_submission_query_and_worker_routing(self):
        from pathlib import Path
        from scripts.codex_form_worker import build_payroll_prompt

        response = self.client.post(
            reverse('payroll-job-create'),
            data={
                'room_type': 'z5-mud',
                'schedule_image': SimpleUploadedFile('schedule.png', b'schedule', content_type='image/png'),
                'host_data': SimpleUploadedFile('host-data.xlsx', b'data'),
            },
        )
        self.assertEqual(response.status_code, 201)
        job_id = response.json()['id']
        task = self.client.get(reverse('worker-task-detail', args=[job_id])).json()
        self.assertEqual(task['task_label'], '薪资计算 · Z5 泥膜直播间')
        self.assertEqual(PayrollJob.objects.get(pk=job_id).get_room_type_display(), 'Z5 泥膜直播间')

        claimed = self.post_json(reverse('payroll-worker-job-next')).json()
        self.assertEqual(claimed['job']['room_type'], 'z5-mud')
        skill_path = Path('/shared/live-payroll/SKILL.md')
        prompt = build_payroll_prompt(claimed, [], Path('result.xlsx'), skill_path=skill_path)
        self.assertIn(skill_path.as_posix(), prompt)
        self.assertIn('z5-mud', prompt)
        self.assertIn('Z5 泥膜直播间', prompt)
        self.assertNotIn('generate_z5_payroll.mjs', prompt)

        claimed['job']['room_type'] = 'z2-eye'
        existing_prompt = build_payroll_prompt(claimed, [], Path('result.xlsx'), skill_path=skill_path)
        self.assertIn(skill_path.as_posix(), existing_prompt)
        self.assertIn('z2-eye', existing_prompt)
        self.assertNotIn('generate_z5_payroll.mjs', existing_prompt)

    def test_expense_submission_accepts_purchase_screenshots_without_invoices(self):
        response = self.client.post(
            reverse('form-automation-job-create'),
            data={
                'form_type': FormAutomationJob.FormType.EXPENSE,
                'purchase_screenshots': SimpleUploadedFile(
                    '未开票物品-购买信息.png',
                    b'purchase',
                    content_type='image/png',
                ),
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['asset_counts']['purchase_screenshots'], 1)
        self.assertEqual(response.json()['asset_counts'].get('invoices', 0), 0)

    def test_expense_submission_accepts_more_than_one_hundred_files(self):
        purchase_files = [
            SimpleUploadedFile(
                f'物品{i:03d}-购买信息.jpg',
                b'purchase',
                content_type='image/jpeg',
            )
            for i in range(56)
        ]
        invoice_files = [
            SimpleUploadedFile(
                f'物品{i:03d}-发票.pdf',
                b'invoice',
                content_type='application/pdf',
            )
            for i in range(56)
        ]

        response = self.client.post(
            reverse('form-automation-job-create'),
            data={
                'form_type': FormAutomationJob.FormType.EXPENSE,
                'purchase_screenshots': purchase_files,
                'invoices': invoice_files,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['asset_counts']['purchase_screenshots'], 56)
        self.assertEqual(response.json()['asset_counts']['invoices'], 56)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FILES=1)
    def test_expense_submission_reports_file_count_limit(self):
        response = self.client.post(
            reverse('form-automation-job-create'),
            data={
                'form_type': FormAutomationJob.FormType.EXPENSE,
                'purchase_screenshots': [
                    SimpleUploadedFile('物品1.jpg', b'1', content_type='image/jpeg'),
                    SimpleUploadedFile('物品2.jpg', b'2', content_type='image/jpeg'),
                ],
            },
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()['error'], 'too_many_files')
        self.assertEqual(response.json()['upload_limit_files'], 1)

    def test_invoice_matching_does_not_fall_back_to_file_position(self):
        unrelated_invoice = SimpleNamespace(original_name='数据线-发票.pdf')

        matched = match_invoice_for_group('未开票物品', [unrelated_invoice], 0)

        self.assertIsNone(matched)

    def test_invoice_matching_keeps_a_unique_filename_match(self):
        expected_invoice = SimpleNamespace(original_name='数据线-发票.pdf')

        matched = match_invoice_for_group('5米数据线', [expected_invoice], 0)

        self.assertIs(matched, expected_invoice)

    def test_payroll_submission_rejects_missing_combined_schedule_image(self):
        response = self.client.post(
            reverse('payroll-job-create'),
            data={
                'room_type': 'z3-polish',
                'host_data': SimpleUploadedFile('host-data.xlsx', b'data'),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['missing_files'], ['schedule_image'])

    def test_payroll_submission_rejects_wrong_file_types(self):
        response = self.client.post(
            reverse('payroll-job-create'),
            data={
                'room_type': 'z3-polish',
                'schedule_image': SimpleUploadedFile('schedule.pdf', b'schedule', content_type='application/pdf'),
                'host_data': SimpleUploadedFile('host-data.csv', b'data', content_type='text/csv'),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['invalid_files'], ['schedule_image', 'host_data'])

    def test_legacy_payroll_jobs_keep_their_original_file_list(self):
        job = PayrollJob.objects.create(
            owner=self.user,
            room_type='z4-neck',
            host_schedule=SimpleUploadedFile('host.xlsx', b'host'),
            controller_schedule=SimpleUploadedFile('controller.xlsx', b'controller'),
            trial_schedule=SimpleUploadedFile('trial.xlsx', b'trial'),
            host_data=SimpleUploadedFile('data.xlsx', b'data'),
        )

        payload = serialize_payroll_job(job)

        self.assertEqual([item['field'] for item in payload['files']], [
            'host_schedule',
            'controller_schedule',
            'trial_schedule',
            'host_data',
        ])

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

    def test_numeric_douyin_id_resolves_from_live_room_page(self):
        class Response:
            text = '{"owner":{"sec_uid":"MS4wLjABAAAA-test-sec-uid"}}'

            @staticmethod
            def raise_for_status():
                return None

        class Http:
            requested_url = ''

            def get(self, url, **_kwargs):
                self.requested_url = url
                return Response()

        http = Http()

        sec_uid = monitor_manager._resolve_sec_uid(http, '95970755567')

        self.assertEqual(sec_uid, 'MS4wLjABAAAA-test-sec-uid')
        self.assertEqual(http.requested_url, 'https://live.douyin.com/95970755567')

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


class GuardLicenseTests(TestCase):
    machine_code = 'a' * 64

    def setUp(self):
        self.license = GuardLicense.objects.create(
            licensee_name='测试直播间',
            max_devices=1,
            offline_grace_days=7,
        )

    def post_json(self, name, payload):
        return self.client.post(
            reverse(name),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_desktop_can_activate_without_site_login_and_validate_token(self):
        activation = self.post_json(
            'guard-license-activate',
            {
                'activation_code': self.license.activation_code.lower(),
                'machine_code': self.machine_code,
                'app_version': '2.5',
            },
        )
        self.assertEqual(activation.status_code, 200)
        payload = activation.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['license']['licensee_name'], '测试直播间')
        self.assertEqual(payload['license']['offline_grace_days'], 7)

        validation = self.post_json(
            'guard-license-validate',
            {
                'machine_code': self.machine_code,
                'device_token': payload['device_token'],
                'app_version': '2.5',
            },
        )
        self.assertEqual(validation.status_code, 200)
        self.assertTrue(validation.json()['ok'])
        self.assertEqual(GuardLicenseDevice.objects.get().app_version, '2.5')

    def test_device_limit_requires_admin_to_release_old_device(self):
        first = self.post_json(
            'guard-license-activate',
            {
                'activation_code': self.license.activation_code,
                'machine_code': self.machine_code,
                'app_version': '2.5',
            },
        )
        self.assertEqual(first.status_code, 200)
        second = self.post_json(
            'guard-license-activate',
            {
                'activation_code': self.license.activation_code,
                'machine_code': 'b' * 64,
                'app_version': '2.5',
            },
        )
        self.assertEqual(second.status_code, 403)
        self.assertEqual(second.json()['code'], 'device_limit')

        device = GuardLicenseDevice.objects.get(machine_code=self.machine_code)
        device.is_revoked = True
        device.save(update_fields=['is_revoked'])
        retry = self.post_json(
            'guard-license-activate',
            {
                'activation_code': self.license.activation_code,
                'machine_code': 'b' * 64,
                'app_version': '2.5',
            },
        )
        self.assertEqual(retry.status_code, 200)

        old_device_retry = self.post_json(
            'guard-license-activate',
            {
                'activation_code': self.license.activation_code,
                'machine_code': self.machine_code,
                'app_version': '2.5',
            },
        )
        self.assertEqual(old_device_retry.status_code, 403)
        self.assertEqual(old_device_retry.json()['code'], 'device_limit')

    def test_suspended_and_expired_license_cannot_be_used(self):
        self.license.status = GuardLicense.Status.SUSPENDED
        self.license.save(update_fields=['status'])
        suspended = self.post_json(
            'guard-license-activate',
            {
                'activation_code': self.license.activation_code,
                'machine_code': self.machine_code,
            },
        )
        self.assertEqual(suspended.status_code, 403)
        self.assertEqual(suspended.json()['code'], 'suspended')

        self.license.status = GuardLicense.Status.ACTIVE
        self.license.expires_at = timezone.now() - timedelta(seconds=1)
        self.license.save(update_fields=['status', 'expires_at'])
        expired = self.post_json(
            'guard-license-activate',
            {
                'activation_code': self.license.activation_code,
                'machine_code': self.machine_code,
            },
        )
        self.assertEqual(expired.status_code, 403)
        self.assertEqual(expired.json()['code'], 'expired')

    def test_admin_has_guard_license_management_page(self):
        admin_user = User.objects.create_superuser(
            username='license-admin',
            email='license-admin@example.com',
            password='StrongAdminPass123!',
        )
        self.client.force_login(admin_user)
        response = self.client.get(reverse('admin:core_guardlicense_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '卫士软件授权')
        GuardLicenseDevice.objects.create(
            license=self.license,
            machine_code=self.machine_code,
            token_hash='1' * 64,
        )
        detail = self.client.get(reverse('admin:core_guardlicense_change', args=[self.license.id]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, '<code class="guard-machine-code">' + self.machine_code + '</code>', html=True)
        self.assertContains(detail, 'core/admin/guard-license.css')
        self.assertContains(detail, 'guard-device-inline')
