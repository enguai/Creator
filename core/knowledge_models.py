import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import get_valid_filename


def knowledge_question_asset_path(instance, filename):
    return f'knowledge_questions/{instance.job_id}/uploads/{get_valid_filename(filename)}'


def knowledge_question_result_path(instance, filename):
    return f'knowledge_questions/{instance.id}/results/{get_valid_filename(filename)}'


class KnowledgeCategory(models.Model):
    name = models.CharField('分类名称', max_length=60)
    parent = models.ForeignKey('self', verbose_name='上级分类', null=True, blank=True,
                               on_delete=models.PROTECT, related_name='children')
    order = models.PositiveIntegerField('排序（小的在前）', default=0)
    is_active = models.BooleanField('启用', default=True)

    class Meta:
        verbose_name = '知识分类'
        verbose_name_plural = verbose_name
        ordering = ('order', 'id')

    def __str__(self):
        return self.name

    def clean(self):
        seen = {self.pk} if self.pk else set()
        parent = self.parent
        while parent:
            if parent.pk in seen:
                raise ValidationError({'parent': '上级分类不能是自身或自己的下级分类。'})
            seen.add(parent.pk)
            parent = parent.parent


class KnowledgeArticle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    is_active = models.BooleanField('启用', default=True)
    published_revision = models.ForeignKey('KnowledgeRevision', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+', verbose_name='当前发布版本')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '知识条目'
        verbose_name_plural = verbose_name


class KnowledgeRevision(models.Model):
    PLATFORMS = [('all', '通用'), ('douyin', '抖音'), ('channels', '视频号'),
                 ('redbook', '小红书'), ('tmall', '天猫'), ('kuaishou', '快手'), ('pdd', '拼多多')]
    STATUSES = [('draft', '草稿'), ('pending', '待审核'), ('published', '已发布'),
                ('returned', '已退回'), ('archived', '历史版本'), ('disabled', '已停用')]
    article = models.ForeignKey(KnowledgeArticle, on_delete=models.CASCADE, related_name='revisions', verbose_name='知识条目')
    version = models.PositiveIntegerField('版本号', default=1)
    title = models.CharField('教程标题', max_length=200)
    summary = models.TextField('简要答案', max_length=1000)
    steps = models.TextField('快速处理步骤', help_text='每行一个步骤，审核发布时必须有 3～5 步。')
    body = models.TextField('完整教程', help_text='填写网站内完整教程，用空行分段；正文按纯文本展示。')
    category = models.ForeignKey(KnowledgeCategory, on_delete=models.PROTECT, verbose_name='知识分类')
    platform = models.CharField('适用平台', max_length=20, choices=PLATFORMS, default='all')
    keywords = models.TextField('搜索关键词 / 常见问法', blank=True, help_text='每行一个词组或问法，如：麦克风没声音。')
    featured = models.BooleanField('列入常见问题', default=False)
    tool_path = models.CharField('相关工具', max_length=80, blank=True,
        choices=[('', '无'), ('/features', '工具库'), ('/features/live-monitor', '直播监控')])
    status = models.CharField('审核状态', max_length=20, choices=STATUSES, default='draft')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                               related_name='+', verbose_name='编写人员')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='+', verbose_name='审核人员')
    review_note = models.TextField('审核意见', blank=True)
    updated_at = models.DateTimeField('编辑时间', auto_now=True)
    published_at = models.DateTimeField('发布时间', null=True, blank=True)

    class Meta:
        verbose_name = '教程与审核'
        verbose_name_plural = verbose_name
        ordering = ('-updated_at',)
        constraints = [models.UniqueConstraint(fields=('article', 'version'), name='knowledge_unique_version')]
        permissions = [('review_knowledge', '审核、发布及停用知识内容')]

    def __str__(self):
        return f'{self.title} · V{self.version}.0'

    def validate_publication(self):
        if not all(value.strip() for value in (self.title, self.summary, self.body)):
            raise ValidationError('请完整填写标题、简要答案和完整教程。')
        if not 3 <= len([line for line in self.steps.splitlines() if line.strip()]) <= 5:
            raise ValidationError('快速处理步骤必须为 3～5 步，每行一个步骤。')
        category = self.category
        while category:
            if not category.is_active:
                raise ValidationError('该分类或上级分类已停用，请先启用或更换分类。')
            category = category.parent


class KnowledgeQuestionJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '等待处理'
        RUNNING = 'running', '正在处理'
        SUCCESS = 'success', '处理成功'
        FAILED = 'failed', '处理失败'

    id = models.UUIDField('任务 ID', primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey('KnowledgeConversation', on_delete=models.CASCADE, null=True, blank=True,
                                     related_name='question_jobs', verbose_name='所属对话')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                              blank=True, related_name='knowledge_question_jobs', verbose_name='提问用户')
    question = models.TextField('用户问题', max_length=500)
    status = models.CharField('任务状态', max_length=20, choices=Status.choices, default=Status.PENDING)
    answer = models.TextField('Codex 答案', blank=True)
    result_file = models.FileField('结果文件', upload_to=knowledge_question_result_path, blank=True)
    citations = models.JSONField('来源教程', default=list, blank=True)
    summary = models.JSONField('处理摘要', default=dict, blank=True)
    progress = models.PositiveSmallIntegerField('处理进度（%）', default=0)
    progress_message = models.CharField('进度说明', max_length=200, default='等待 Worker 处理')
    worker_id = models.CharField('处理节点', max_length=120, blank=True)
    claim_token = models.UUIDField('领取令牌', null=True, blank=True, editable=False)
    lease_expires_at = models.DateTimeField('任务租约到期时间', null=True, blank=True)
    attempt_count = models.PositiveSmallIntegerField('处理次数', default=0)
    started_at = models.DateTimeField('开始处理时间', null=True, blank=True)
    finished_at = models.DateTimeField('处理完成时间', null=True, blank=True)
    error_message = models.TextField('失败原因', blank=True)
    created_at = models.DateTimeField('提交时间', auto_now_add=True)
    updated_at = models.DateTimeField('最后更新时间', auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Codex 知识问答任务'
        verbose_name_plural = 'Codex 知识问答任务'
        indexes = [
            models.Index(fields=['status', 'created_at'], name='knowledge_q_status_created_idx'),
            models.Index(fields=['status', 'lease_expires_at'], name='knowledge_q_status_lease_idx'),
        ]

    def __str__(self):
        return f'知识问答 {self.id}（{self.get_status_display()}）'


class KnowledgeQuestionAsset(models.Model):
    job = models.ForeignKey(
        KnowledgeQuestionJob,
        on_delete=models.CASCADE,
        related_name='assets',
        verbose_name='所属问答任务',
    )
    file = models.FileField('数据源文件', upload_to=knowledge_question_asset_path)
    original_name = models.CharField('原始文件名', max_length=255)
    size = models.PositiveBigIntegerField('文件大小', default=0)
    content_type = models.CharField('文件类型', max_length=120, blank=True)
    created_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = '知识问答数据源'
        verbose_name_plural = '知识问答数据源'

    def __str__(self):
        return f'{self.original_name} · {self.job_id}'


class KnowledgeConversation(models.Model):
    id = models.UUIDField('对话 ID', primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='knowledge_conversations', verbose_name='所属用户')
    title = models.CharField('对话标题', max_length=120, default='新对话')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('最后更新时间', auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = 'Codex 对话'
        verbose_name_plural = 'Codex 对话'

    def __str__(self):
        return f'{self.title} · {self.owner}'


class KnowledgeMessage(models.Model):
    class Role(models.TextChoices):
        USER = 'user', '用户'
        ASSISTANT = 'assistant', 'Codex'

    conversation = models.ForeignKey(KnowledgeConversation, on_delete=models.CASCADE,
                                     related_name='messages', verbose_name='所属对话')
    job = models.ForeignKey(KnowledgeQuestionJob, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name='messages', verbose_name='关联任务')
    role = models.CharField('角色', max_length=20, choices=Role.choices)
    content = models.TextField('消息内容', max_length=20000)
    created_at = models.DateTimeField('发送时间', auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        verbose_name = 'Codex 消息'
        verbose_name_plural = 'Codex 消息'
        indexes = [
            models.Index(fields=['conversation', 'created_at'], name='knowledge_msg_conversation_idx'),
        ]
