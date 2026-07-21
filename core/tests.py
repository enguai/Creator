import json
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import unquote

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import FormAutomationJob, PayrollJob


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
        return FormAutomationJob.objects.create(**values)

    def create_payroll_job(self):
        return PayrollJob.objects.create(
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
