from django.db import migrations, models


TRACKING_FIELDS = (
    ('progress', models.PositiveSmallIntegerField(default=0)),
    ('progress_message', models.CharField(default='等待 Worker 处理', max_length=200)),
    ('worker_id', models.CharField(blank=True, max_length=120)),
    ('claim_token', models.UUIDField(blank=True, editable=False, null=True)),
    ('lease_expires_at', models.DateTimeField(blank=True, null=True)),
    ('attempt_count', models.PositiveSmallIntegerField(default=0)),
    ('started_at', models.DateTimeField(blank=True, null=True)),
    ('finished_at', models.DateTimeField(blank=True, null=True)),
)


def backfill_worker_tracking(apps, _schema_editor):
    for model_name in ('PayrollJob', 'FormAutomationJob'):
        model = apps.get_model('core', model_name)
        model.objects.filter(status='success').update(
            progress=100,
            progress_message='处理成功',
            finished_at=models.F('updated_at'),
        )
        model.objects.filter(status='failed').update(
            progress_message='处理失败',
            finished_at=models.F('updated_at'),
        )
        model.objects.filter(status='running').update(
            status='pending',
            progress=0,
            progress_message='系统升级后等待重新处理',
            worker_id='',
            claim_token=None,
            lease_expires_at=None,
            started_at=None,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_payrolljob_summary'),
    ]

    operations = [
        *[
            migrations.AddField(model_name=model_name, name=name, field=field.clone())
            for model_name in ('payrolljob', 'formautomationjob')
            for name, field in TRACKING_FIELDS
        ],
        migrations.RunPython(backfill_worker_tracking, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='payrolljob',
            index=models.Index(fields=['status', 'created_at'], name='payroll_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='payrolljob',
            index=models.Index(fields=['status', 'lease_expires_at'], name='payroll_status_lease_idx'),
        ),
        migrations.AddIndex(
            model_name='formautomationjob',
            index=models.Index(fields=['status', 'created_at'], name='form_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='formautomationjob',
            index=models.Index(fields=['status', 'lease_expires_at'], name='form_status_lease_idx'),
        ),
    ]
