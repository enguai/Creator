import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


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
