from django.db import models
from django.contrib.auth.models import User
from django.utils.text import get_valid_filename

import uuid


def payroll_output_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'payroll/{instance.id}/outputs/{safe_name}'


def payroll_host_schedule_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'payroll/{instance.id}/uploads/host_schedule/{safe_name}'


def payroll_controller_schedule_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'payroll/{instance.id}/uploads/controller_schedule/{safe_name}'


def payroll_trial_schedule_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'payroll/{instance.id}/uploads/trial_schedule/{safe_name}'


def payroll_host_data_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'payroll/{instance.id}/uploads/host_data/{safe_name}'


def form_output_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'form_automation/{instance.id}/outputs/{safe_name}'


def form_asset_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'form_automation/{instance.job_id}/uploads/{instance.group}/{safe_name}'


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    nickname = models.CharField(max_length=50)

    def __str__(self):
        return self.nickname


class PayrollJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_type = models.CharField(max_length=40, default='general')
    week_start = models.DateField(null=True, blank=True)
    week_end = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    host_schedule = models.FileField(upload_to=payroll_host_schedule_path)
    controller_schedule = models.FileField(upload_to=payroll_controller_schedule_path)
    trial_schedule = models.FileField(upload_to=payroll_trial_schedule_path)
    host_data = models.FileField(upload_to=payroll_host_data_path)
    result_file = models.FileField(upload_to=payroll_output_path, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    progress_message = models.CharField(max_length=200, default='等待 Worker 处理')
    worker_id = models.CharField(max_length=120, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at'], name='payroll_status_created_idx'),
            models.Index(fields=['status', 'lease_expires_at'], name='payroll_status_lease_idx'),
        ]

    def __str__(self):
        return f'Payroll job {self.id} ({self.status})'


class FormAutomationJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'

    class FormType(models.TextChoices):
        EXPENSE = 'expense', 'Expense reimbursement'
        PROCUREMENT = 'procurement', 'Procurement request'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    form_type = models.CharField(max_length=30, choices=FormType.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    result_file = models.FileField(upload_to=form_output_path, blank=True)
    summary = models.JSONField(default=dict, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    progress_message = models.CharField(max_length=200, default='等待 Worker 处理')
    worker_id = models.CharField(max_length=120, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at'], name='form_status_created_idx'),
            models.Index(fields=['status', 'lease_expires_at'], name='form_status_lease_idx'),
        ]

    def __str__(self):
        return f'Form automation job {self.id} ({self.form_type}, {self.status})'


class FormAutomationAsset(models.Model):
    job = models.ForeignKey(FormAutomationJob, on_delete=models.CASCADE, related_name='assets')
    group = models.CharField(max_length=40)
    file = models.FileField(upload_to=form_asset_path)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['group', 'original_name']

    def __str__(self):
        return f'{self.group}: {self.original_name}'


class DouyinMonitorConfig(models.Model):
    class Mode(models.TextChoices):
        GREATER = 'greater', 'Greater than'
        LESS = 'less', 'Less than'
        RANGE = 'range', 'Range'

    douyin_id = models.CharField(max_length=120, unique=True)
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=20, choices=Mode.choices, default=Mode.GREATER)
    threshold = models.PositiveIntegerField(default=100)
    min_count = models.PositiveIntegerField(default=50)
    max_count = models.PositiveIntegerField(default=100)
    cooldown_enabled = models.BooleanField(default=False)
    cooldown_minutes = models.PositiveIntegerField(default=10)
    webhook = models.TextField(blank=True)
    secret = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Douyin monitor config {self.douyin_id}'


class DouyinMonitorSession(models.Model):
    class Status(models.TextChoices):
        STARTING = 'starting', 'Starting'
        RESOLVING = 'resolving', 'Resolving'
        CONNECTING = 'connecting', 'Connecting'
        MONITORING = 'monitoring', 'Monitoring'
        WARNING = 'warning', 'Warning'
        ERROR = 'error', 'Error'
        STOPPED = 'stopped', 'Stopped'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    douyin_id = models.CharField(max_length=120)
    room_title = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.STARTING)
    status_message = models.CharField(max_length=300, default='正在建立独立匿名连接')
    current_count = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=300, blank=True)
    sec_uid = models.CharField(max_length=200, blank=True)
    room_id = models.CharField(max_length=80, blank=True)
    web_rid = models.CharField(max_length=80, blank=True)
    stream_url = models.TextField(blank=True)
    points = models.JSONField(default=list, blank=True)
    alerts = models.JSONField(default=list, blank=True)
    config = models.JSONField(default=dict, blank=True)
    last_alert_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['status', 'started_at'], name='douyin_status_started_idx'),
        ]

    def __str__(self):
        return f'Douyin monitor {self.douyin_id} ({self.status})'
