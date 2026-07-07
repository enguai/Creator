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
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Payroll job {self.id} ({self.status})'
