import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_knowledge_defaults'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='KnowledgeQuestionJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='任务 ID')),
                ('question', models.TextField(max_length=500, verbose_name='用户问题')),
                ('status', models.CharField(choices=[('pending', '等待处理'), ('running', '正在处理'), ('success', '处理成功'), ('failed', '处理失败')], default='pending', max_length=20, verbose_name='任务状态')),
                ('answer', models.TextField(blank=True, verbose_name='Codex 答案')),
                ('citations', models.JSONField(blank=True, default=list, verbose_name='来源教程')),
                ('summary', models.JSONField(blank=True, default=dict, verbose_name='处理摘要')),
                ('progress', models.PositiveSmallIntegerField(default=0, verbose_name='处理进度（%）')),
                ('progress_message', models.CharField(default='等待 Worker 处理', max_length=200, verbose_name='进度说明')),
                ('worker_id', models.CharField(blank=True, max_length=120, verbose_name='处理节点')),
                ('claim_token', models.UUIDField(blank=True, editable=False, null=True, verbose_name='领取令牌')),
                ('lease_expires_at', models.DateTimeField(blank=True, null=True, verbose_name='任务租约到期时间')),
                ('attempt_count', models.PositiveSmallIntegerField(default=0, verbose_name='处理次数')),
                ('started_at', models.DateTimeField(blank=True, null=True, verbose_name='开始处理时间')),
                ('finished_at', models.DateTimeField(blank=True, null=True, verbose_name='处理完成时间')),
                ('error_message', models.TextField(blank=True, verbose_name='失败原因')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='提交时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='最后更新时间')),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='knowledge_question_jobs', to=settings.AUTH_USER_MODEL, verbose_name='提问用户')),
            ],
            options={
                'verbose_name': 'Codex 知识问答任务',
                'verbose_name_plural': 'Codex 知识问答任务',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['status', 'created_at'], name='knowledge_q_status_created_idx'), models.Index(fields=['status', 'lease_expires_at'], name='knowledge_q_status_lease_idx')],
            },
        ),
    ]
