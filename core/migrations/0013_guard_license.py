import core.models
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0012_payroll_combined_schedule_and_rating_update'),
    ]

    operations = [
        migrations.CreateModel(
            name='GuardLicense',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='授权编号')),
                ('activation_code', models.CharField(default=core.models.generate_guard_activation_code, editable=False, max_length=32, unique=True, verbose_name='激活码')),
                ('licensee_name', models.CharField(max_length=120, verbose_name='被授权人或单位')),
                ('status', models.CharField(choices=[('active', '正常'), ('suspended', '暂停使用'), ('revoked', '已撤销')], default='active', max_length=20, verbose_name='授权状态')),
                ('expires_at', models.DateTimeField(blank=True, null=True, verbose_name='到期时间')),
                ('max_devices', models.PositiveSmallIntegerField(default=1, verbose_name='允许电脑数量')),
                ('offline_grace_days', models.PositiveSmallIntegerField(default=7, verbose_name='断网宽限天数')),
                ('notes', models.TextField(blank=True, verbose_name='备注')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
            ],
            options={
                'verbose_name': '卫士软件授权',
                'verbose_name_plural': '卫士软件授权',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['status', 'expires_at'], name='guard_license_status_idx')],
            },
        ),
        migrations.CreateModel(
            name='GuardLicenseDevice',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='设备编号')),
                ('machine_code', models.CharField(max_length=64, verbose_name='机器码摘要')),
                ('token_hash', models.CharField(editable=False, max_length=64, unique=True, verbose_name='设备令牌摘要')),
                ('app_version', models.CharField(blank=True, max_length=30, verbose_name='软件版本')),
                ('is_revoked', models.BooleanField(default=False, verbose_name='设备已解绑')),
                ('last_ip', models.GenericIPAddressField(blank=True, null=True, verbose_name='最近 IP')),
                ('activated_at', models.DateTimeField(auto_now_add=True, verbose_name='首次激活时间')),
                ('last_seen_at', models.DateTimeField(auto_now=True, verbose_name='最近验证时间')),
                ('license', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='devices', to='core.guardlicense', verbose_name='所属授权')),
            ],
            options={
                'verbose_name': '卫士授权设备',
                'verbose_name_plural': '卫士授权设备',
                'ordering': ['-last_seen_at'],
                'indexes': [models.Index(fields=['license', 'is_revoked'], name='guard_device_active_idx')],
                'constraints': [models.UniqueConstraint(fields=('license', 'machine_code'), name='guard_license_machine_unique')],
            },
        ),
    ]
