import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_knowledgequestionjob'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='KnowledgeConversation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='对话 ID')),
                ('title', models.CharField(default='新对话', max_length=120, verbose_name='对话标题')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='最后更新时间')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='knowledge_conversations', to=settings.AUTH_USER_MODEL, verbose_name='所属用户')),
            ],
            options={
                'verbose_name': 'Codex 对话',
                'verbose_name_plural': 'Codex 对话',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddField(
            model_name='knowledgequestionjob',
            name='conversation',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='question_jobs', to='core.knowledgeconversation', verbose_name='所属对话'),
        ),
        migrations.CreateModel(
            name='KnowledgeMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('user', '用户'), ('assistant', 'Codex')], max_length=20, verbose_name='角色')),
                ('content', models.TextField(max_length=20000, verbose_name='消息内容')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='发送时间')),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='core.knowledgeconversation', verbose_name='所属对话')),
                ('job', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='messages', to='core.knowledgequestionjob', verbose_name='关联任务')),
            ],
            options={
                'verbose_name': 'Codex 消息',
                'verbose_name_plural': 'Codex 消息',
                'ordering': ['created_at', 'id'],
                'indexes': [models.Index(fields=['conversation', 'created_at'], name='knowledge_msg_conversation_idx')],
            },
        ),
    ]
