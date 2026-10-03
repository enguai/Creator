from django.db import models
from django.contrib.auth.models import User
from django.utils.text import get_valid_filename

import secrets
import uuid


GUARD_LICENSE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'


def generate_guard_activation_code():
    groups = [
        ''.join(secrets.choice(GUARD_LICENSE_ALPHABET) for _index in range(5))
        for _group in range(4)
    ]
    return f'LAG-{"-".join(groups)}'


def payroll_output_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'payroll/{instance.id}/outputs/{safe_name}'


def payroll_schedule_image_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'payroll/{instance.id}/uploads/schedule_image/{safe_name}'


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


def payroll_rating_update_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'payroll/{instance.id}/uploads/rating_update/{safe_name}'


def form_output_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'form_automation/{instance.id}/outputs/{safe_name}'


def form_asset_path(instance, filename):
    safe_name = get_valid_filename(filename)
    return f'form_automation/{instance.job_id}/uploads/{instance.group}/{safe_name}'


class Profile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='用户账号',
    )
    nickname = models.CharField('昵称', max_length=50)

    class Meta:
        verbose_name = '用户资料'
        verbose_name_plural = '用户资料'

    def __str__(self):
        return self.nickname


class GuardLicense(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', '正常'
        SUSPENDED = 'suspended', '暂停使用'
        REVOKED = 'revoked', '已撤销'

    id = models.UUIDField('授权编号', primary_key=True, default=uuid.uuid4, editable=False)
    activation_code = models.CharField(
        '激活码',
        max_length=32,
        unique=True,
        default=generate_guard_activation_code,
        editable=False,
    )
    licensee_name = models.CharField('被授权人或单位', max_length=120)
    status = models.CharField(
        '授权状态',
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    expires_at = models.DateTimeField('到期时间', null=True, blank=True)
    max_devices = models.PositiveSmallIntegerField('允许电脑数量', default=1)
    offline_grace_days = models.PositiveSmallIntegerField('断网宽限天数', default=7)
    notes = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '卫士软件授权'
        verbose_name_plural = '卫士软件授权'
        indexes = [
            models.Index(fields=['status', 'expires_at'], name='guard_license_status_idx'),
        ]

    def __str__(self):
        return f'{self.licensee_name}（{self.activation_code}）'


class GuardLicenseDevice(models.Model):
    id = models.UUIDField('设备编号', primary_key=True, default=uuid.uuid4, editable=False)
    license = models.ForeignKey(
        GuardLicense,
        on_delete=models.CASCADE,
        related_name='devices',
        verbose_name='所属授权',
    )
    machine_code = models.CharField('机器码摘要', max_length=64)
    token_hash = models.CharField('设备令牌摘要', max_length=64, unique=True, editable=False)
    app_version = models.CharField('软件版本', max_length=30, blank=True)
    is_revoked = models.BooleanField('设备已解绑', default=False)
    last_ip = models.GenericIPAddressField('最近 IP', null=True, blank=True)
    activated_at = models.DateTimeField('首次激活时间', auto_now_add=True)
    last_seen_at = models.DateTimeField('最近验证时间', auto_now=True)

    class Meta:
        ordering = ['-last_seen_at']
        verbose_name = '卫士授权设备'
        verbose_name_plural = '卫士授权设备'
        constraints = [
            models.UniqueConstraint(
                fields=['license', 'machine_code'],
                name='guard_license_machine_unique',
            ),
        ]
        indexes = [
            models.Index(fields=['license', 'is_revoked'], name='guard_device_active_idx'),
        ]

    def __str__(self):
        return f'{self.license.licensee_name} · {self.machine_code[:12]}'


class PayrollJob(models.Model):
    class RoomType(models.TextChoices):
        GENERAL = 'general', '通用直播间'
        NECK_MASK = 'z4-neck', 'Z4 颈膜直播间'
        EYE_MASK = 'z2-eye', 'Z2 眼膜直播间'
        POLISH_MASK = 'z3-polish', 'Z3 抛光直播间'
        MUD_MASK = 'z5-mud', 'Z5 泥膜直播间'

    class Status(models.TextChoices):
        PENDING = 'pending', '等待处理'
        RUNNING = 'running', '正在处理'
        SUCCESS = 'success', '处理成功'
        FAILED = 'failed', '处理失败'

    id = models.UUIDField('任务 ID', primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='payroll_jobs', verbose_name='提交用户')
    room_type = models.CharField('直播间类型', max_length=40, choices=RoomType.choices, default=RoomType.GENERAL)
    week_start = models.DateField('周期开始日期', null=True, blank=True)
    week_end = models.DateField('周期结束日期', null=True, blank=True)
    status = models.CharField(
        '任务状态',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    schedule_image = models.FileField('综合排班表图片', upload_to=payroll_schedule_image_path, blank=True)
    host_schedule = models.FileField('主播排班表（旧版）', upload_to=payroll_host_schedule_path, blank=True)
    controller_schedule = models.FileField('场控排班表（旧版）', upload_to=payroll_controller_schedule_path, blank=True)
    trial_schedule = models.FileField('试播排班表（旧版）', upload_to=payroll_trial_schedule_path, blank=True)
    host_data = models.FileField('兼职主播数据表', upload_to=payroll_host_data_path)
    rating_update = models.FileField('兼职评级更新', upload_to=payroll_rating_update_path, blank=True)
    result_file = models.FileField('结果文件', upload_to=payroll_output_path, blank=True)
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
        verbose_name = '薪资计算任务'
        verbose_name_plural = '薪资计算任务'
        indexes = [
            models.Index(fields=['status', 'created_at'], name='payroll_status_created_idx'),
            models.Index(fields=['status', 'lease_expires_at'], name='payroll_status_lease_idx'),
        ]

    def __str__(self):
        return f'薪资计算任务 {self.id}（{self.get_status_display()}）'


class FormAutomationJob(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '等待处理'
        RUNNING = 'running', '正在处理'
        SUCCESS = 'success', '处理成功'
        FAILED = 'failed', '处理失败'

    class FormType(models.TextChoices):
        EXPENSE = 'expense', '费用报销表'
        PROCUREMENT = 'procurement', '采购申请表'

    id = models.UUIDField('任务 ID', primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='form_automation_jobs', verbose_name='提交用户')
    form_type = models.CharField('表格类型', max_length=30, choices=FormType.choices)
    status = models.CharField(
        '任务状态',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    result_file = models.FileField('结果文件', upload_to=form_output_path, blank=True)
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
        verbose_name = '报销与采购任务'
        verbose_name_plural = '报销与采购任务'
        indexes = [
            models.Index(fields=['status', 'created_at'], name='form_status_created_idx'),
            models.Index(fields=['status', 'lease_expires_at'], name='form_status_lease_idx'),
        ]

    def __str__(self):
        return f'{self.get_form_type_display()}任务 {self.id}（{self.get_status_display()}）'


class FormAutomationAsset(models.Model):
    job = models.ForeignKey(FormAutomationJob, on_delete=models.CASCADE, related_name='assets', verbose_name='所属任务')
    group = models.CharField('文件分组', max_length=40)
    file = models.FileField('文件', upload_to=form_asset_path)
    original_name = models.CharField('原始文件名', max_length=255)
    size = models.PositiveIntegerField('文件大小（字节）', default=0)
    created_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        ordering = ['group', 'original_name']
        verbose_name = '任务文件'
        verbose_name_plural = '任务文件'

    def __str__(self):
        return f'{self.original_name}（{self.group}）'


class DouyinMonitorConfig(models.Model):
    class Mode(models.TextChoices):
        GREATER = 'greater', '高于阈值'
        LESS = 'less', '低于阈值'
        RANGE = 'range', '指定范围'

    owner = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='douyin_monitor_configs', verbose_name='所属用户')
    douyin_id = models.CharField('抖音号', max_length=120)
    enabled = models.BooleanField('启用告警', default=False)
    mode = models.CharField('告警规则', max_length=20, choices=Mode.choices, default=Mode.GREATER)
    threshold = models.PositiveIntegerField('人数阈值', default=100)
    min_count = models.PositiveIntegerField('最小人数', default=50)
    max_count = models.PositiveIntegerField('最大人数', default=100)
    cooldown_enabled = models.BooleanField('启用告警冷却', default=False)
    cooldown_minutes = models.PositiveIntegerField('冷却时长（分钟）', default=10)
    webhook = models.TextField('飞书 Webhook', blank=True)
    secret = models.TextField('飞书签名密钥', blank=True)
    updated_at = models.DateTimeField('最后更新时间', auto_now=True)

    class Meta:
        verbose_name = '直播告警配置'
        verbose_name_plural = '直播告警配置'
        constraints = [
            models.UniqueConstraint(fields=['owner', 'douyin_id'], name='douyin_owner_id_unique'),
        ]

    def __str__(self):
        return f'{self.douyin_id} 的直播告警配置'


class DouyinMonitorSession(models.Model):
    class Status(models.TextChoices):
        STARTING = 'starting', '正在启动'
        RESOLVING = 'resolving', '正在解析直播间'
        CONNECTING = 'connecting', '正在连接'
        MONITORING = 'monitoring', '监控中'
        WARNING = 'warning', '告警中'
        ERROR = 'error', '异常'
        STOPPED = 'stopped', '已停止'

    id = models.UUIDField('监控 ID', primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='douyin_monitor_sessions', verbose_name='所属用户')
    douyin_id = models.CharField('抖音号', max_length=120)
    room_title = models.CharField('直播间名称', max_length=200, blank=True)
    status = models.CharField('监控状态', max_length=20, choices=Status.choices, default=Status.STARTING)
    status_message = models.CharField('状态说明', max_length=300, default='正在建立独立匿名连接')
    current_count = models.PositiveIntegerField('当前在线人数', null=True, blank=True)
    started_at = models.DateTimeField('开始监控时间', auto_now_add=True)
    ended_at = models.DateTimeField('结束监控时间', null=True, blank=True)
    end_reason = models.CharField('结束原因', max_length=300, blank=True)
    sec_uid = models.CharField('抖音 SecUID', max_length=200, blank=True)
    room_id = models.CharField('直播间 ID', max_length=80, blank=True)
    web_rid = models.CharField('直播间 Web RID', max_length=80, blank=True)
    stream_url = models.TextField('直播流地址', blank=True)
    points = models.JSONField('在线人数曲线数据', default=list, blank=True)
    alerts = models.JSONField('告警记录', default=list, blank=True)
    config = models.JSONField('本次监控配置', default=dict, blank=True)
    last_alert_at = models.DateTimeField('最后告警时间', null=True, blank=True)
    updated_at = models.DateTimeField('最后更新时间', auto_now=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = '直播监控记录'
        verbose_name_plural = '直播监控记录'
        indexes = [
            models.Index(fields=['status', 'started_at'], name='douyin_status_started_idx'),
        ]

    def __str__(self):
        return f'{self.douyin_id} 的直播监控（{self.get_status_display()}）'


class UserSecurityEvent(models.Model):
    class Event(models.TextChoices):
        REGISTERED = 'registered', '注册成功'
        LOGIN_SUCCEEDED = 'login_succeeded', '登录成功'
        LOGIN_FAILED = 'login_failed', '登录失败'
        LOGIN_BLOCKED = 'login_blocked', '登录已限制'
        LOGGED_OUT = 'logged_out', '退出登录'
        ACCOUNT_RECOVERY = 'account_recovery', '申请找回账号'
        PASSWORD_RESET_REQUESTED = 'password_reset_requested', '申请重置密码'
        PASSWORD_RESET_COMPLETED = 'password_reset_completed', '密码重置完成'
        VERIFICATION_CODE_SENT = 'verification_code_sent', '发送验证码'

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='security_events', verbose_name='用户')
    username = models.CharField('账号', max_length=150, blank=True)
    event = models.CharField('事件类型', max_length=40, choices=Event.choices)
    ip_address = models.GenericIPAddressField('IP 地址', null=True, blank=True)
    details = models.JSONField('详细信息', default=dict, blank=True)
    created_at = models.DateTimeField('发生时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '用户安全日志'
        verbose_name_plural = '用户安全日志'
        indexes = [
            models.Index(fields=['event', 'username', 'created_at'], name='security_event_user_idx'),
            models.Index(fields=['ip_address', 'created_at'], name='security_event_ip_idx'),
        ]

    def __str__(self):
        return f'{self.get_event_display()}：{self.username or "匿名用户"}'


class VerificationCode(models.Model):
    class Channel(models.TextChoices):
        EMAIL = 'email', '邮箱'

    class Purpose(models.TextChoices):
        ACCOUNT_RECOVERY = 'account_recovery', '找回用户名'
        PASSWORD_RESET = 'password_reset', '重置密码'

    channel = models.CharField('发送方式', max_length=10, choices=Channel.choices)
    purpose = models.CharField('使用场景', max_length=30, choices=Purpose.choices)
    destination = models.CharField('接收地址', max_length=254, db_index=True)
    code_hash = models.CharField('验证码摘要', max_length=128)
    request_ip = models.GenericIPAddressField('申请 IP', null=True, blank=True)
    failed_attempts = models.PositiveSmallIntegerField('错误次数', default=0)
    expires_at = models.DateTimeField('过期时间')
    consumed_at = models.DateTimeField('使用时间', null=True, blank=True)
    created_at = models.DateTimeField('发送时间', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = '验证码记录'
        verbose_name_plural = '验证码记录'
        indexes = [
            models.Index(
                fields=['channel', 'purpose', 'destination', 'created_at'],
                name='verify_code_lookup_idx',
            ),
        ]

    def __str__(self):
        return f'{self.get_channel_display()}验证码：{self.destination}'


from .knowledge_models import (  # noqa: E402,F401
    KnowledgeArticle,
    KnowledgeCategory,
    KnowledgeConversation,
    KnowledgeMessage,
    KnowledgeQuestionJob,
    KnowledgeRevision,
)
