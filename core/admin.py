from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import User
from django.utils.html import format_html
from . import knowledge_admin  # noqa: F401

from .models import (
    DouyinMonitorConfig,
    DouyinMonitorSession,
    FormAutomationAsset,
    FormAutomationJob,
    GuardLicense,
    GuardLicenseDevice,
    PayrollJob,
    Profile,
    UserSecurityEvent,
)


class CreatorAdminMixin:
    list_per_page = 25
    show_full_result_count = False
    save_on_top = True


class GuardLicenseDeviceInline(admin.TabularInline):
    model = GuardLicenseDevice
    extra = 0
    can_delete = False
    classes = ('guard-device-inline',)

    class Media:
        css = {'all': ('core/admin/guard-license.css',)}
    fields = (
        'device_short_code',
        'app_version',
        'is_revoked',
        'activated_at',
        'last_seen_at',
        'last_ip',
    )
    readonly_fields = (
        'device_short_code',
        'app_version',
        'activated_at',
        'last_seen_at',
        'last_ip',
    )
    verbose_name = '已绑定电脑'
    verbose_name_plural = '已绑定电脑（勾选“设备已解绑”即可释放名额）'

    @admin.display(description='机器码')
    def device_short_code(self, obj):
        if not obj or not obj.machine_code:
            return '保存后显示'
        return format_html('<code class="guard-machine-code">{}</code>', obj.machine_code)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(GuardLicense)
class GuardLicenseAdmin(CreatorAdminMixin, admin.ModelAdmin):
    list_display = (
        'licensee_name',
        'activation_code',
        'status',
        'expires_at',
        'device_usage',
        'offline_grace_days',
        'created_at',
    )
    list_filter = ('status', 'expires_at', 'created_at')
    search_fields = ('licensee_name', 'activation_code', 'notes')
    search_help_text = '可按被授权人、激活码或备注搜索'
    readonly_fields = ('id', 'activation_code', 'created_at', 'updated_at')
    fieldsets = (
        ('授权信息', {'fields': ('id', 'activation_code', 'licensee_name', 'status')}),
        ('使用限制', {'fields': ('expires_at', 'max_devices', 'offline_grace_days')}),
        ('备注与时间', {'fields': ('notes', 'created_at', 'updated_at')}),
    )
    inlines = (GuardLicenseDeviceInline,)
    actions = ('enable_licenses', 'suspend_licenses', 'revoke_licenses')

    @admin.display(description='电脑使用量')
    def device_usage(self, obj):
        used = obj.devices.filter(is_revoked=False).count()
        return f'{used} / {obj.max_devices}'

    @admin.action(description='启用所选授权')
    def enable_licenses(self, request, queryset):
        queryset.update(status=GuardLicense.Status.ACTIVE)

    @admin.action(description='暂停所选授权')
    def suspend_licenses(self, request, queryset):
        queryset.update(status=GuardLicense.Status.SUSPENDED)

    @admin.action(description='撤销所选授权')
    def revoke_licenses(self, request, queryset):
        queryset.update(status=GuardLicense.Status.REVOKED)


def validate_admin_email(email, user=None):
    email = str(email or '').strip().lower()
    if not email:
        raise forms.ValidationError('请输入邮箱。')
    existing = User.objects.filter(email__iexact=email)
    if user and user.pk:
        existing = existing.exclude(pk=user.pk)
    if existing.exists():
        raise forms.ValidationError('该邮箱已经被其他用户使用。')
    return email


class CreatorUserCreationForm(UserCreationForm):
    email = forms.EmailField(label='邮箱', required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email')

    def clean_email(self):
        return validate_admin_email(self.cleaned_data.get('email'))


class CreatorUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = '__all__'

    def clean_email(self):
        return validate_admin_email(self.cleaned_data.get('email'), self.instance)


admin.site.unregister(User)
User._meta.verbose_name = '用户资料'
User._meta.verbose_name_plural = '用户资料'


@admin.register(User)
class CreatorUserAdmin(CreatorAdminMixin, UserAdmin):
    form = CreatorUserChangeForm
    add_form = CreatorUserCreationForm
    list_display = (
        'username',
        'email_address',
        'password_status',
        'active_status',
        'registered_at',
        'recent_login',
    )
    list_filter = ('is_active', 'date_joined', 'last_login')
    search_fields = ('username', 'email')
    search_help_text = '可按用户名或邮箱搜索'
    ordering = ('username',)
    readonly_fields = ('date_joined', 'last_login')
    filter_horizontal = ()
    fieldsets = (
        ('账号信息', {'fields': ('username', 'email', 'password', 'is_active')}),
        ('时间记录', {'fields': ('date_joined', 'last_login')}),
    )
    add_fieldsets = (
        ('新建用户资料', {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'is_active'),
        }),
    )

    def get_fieldsets(self, request, obj=None):
        fields = super().get_fieldsets(request, obj)
        if obj and request.user.is_superuser:
            return (*fields, ('后台权限（仅管理员可分配）', {
                'fields': ('is_staff', 'groups'),
                'description': '需要维护知识的人员，请开启后台访问并分配知识编辑或知识审核组。普通员工无需开启。',
            }))
        return fields

    @admin.display(description='密码')
    def password_status(self, obj):
        return '已加密' if obj.has_usable_password() else '不可用'

    @admin.display(description='邮箱', ordering='email')
    def email_address(self, obj):
        return obj.email

    @admin.display(boolean=True, description='是否激活', ordering='is_active')
    def active_status(self, obj):
        return obj.is_active

    @admin.display(description='注册日期', ordering='date_joined')
    def registered_at(self, obj):
        return obj.date_joined

    @admin.display(description='最近登录', ordering='last_login')
    def recent_login(self, obj):
        return obj.last_login

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        Profile.objects.update_or_create(
            user=obj,
            defaults={
                'nickname': obj.username,
            },
        )


@admin.register(PayrollJob)
class PayrollJobAdmin(CreatorAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'owner', 'room_type', 'status', 'progress', 'created_at')
    list_filter = ('status', 'room_type', 'created_at')
    search_fields = ('id', 'owner__username', 'owner__email', 'error_message')
    search_help_text = '可按任务 ID、用户账号、邮箱或失败原因搜索'
    readonly_fields = ('id', 'claim_token', 'created_at', 'updated_at')
    date_hierarchy = 'created_at'
    list_select_related = ('owner',)


class FormAutomationAssetInline(admin.TabularInline):
    model = FormAutomationAsset
    extra = 0
    readonly_fields = ('created_at',)
    verbose_name = '任务文件'
    verbose_name_plural = '任务文件'


@admin.register(FormAutomationJob)
class FormAutomationJobAdmin(CreatorAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'owner', 'form_type', 'status', 'progress', 'created_at')
    list_filter = ('status', 'form_type', 'created_at')
    search_fields = ('id', 'owner__username', 'owner__email', 'error_message')
    search_help_text = '可按任务 ID、用户账号、邮箱或失败原因搜索'
    readonly_fields = ('id', 'claim_token', 'created_at', 'updated_at')
    inlines = (FormAutomationAssetInline,)
    date_hierarchy = 'created_at'
    list_select_related = ('owner',)


@admin.register(DouyinMonitorSession)
class DouyinMonitorSessionAdmin(CreatorAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'owner', 'douyin_id', 'room_title', 'status', 'current_count', 'started_at', 'ended_at')
    list_filter = ('status', 'started_at')
    search_fields = ('id', 'owner__username', 'douyin_id', 'room_title')
    search_help_text = '可按监控 ID、用户账号、抖音号或直播间名称搜索'
    readonly_fields = ('id', 'started_at', 'updated_at')
    date_hierarchy = 'started_at'
    list_select_related = ('owner',)


@admin.register(DouyinMonitorConfig)
class DouyinMonitorConfigAdmin(CreatorAdminMixin, admin.ModelAdmin):
    list_display = ('douyin_id', 'owner', 'enabled', 'mode', 'threshold', 'cooldown_enabled', 'updated_at')
    list_filter = ('enabled', 'mode', 'cooldown_enabled')
    search_fields = ('owner__username', 'douyin_id')
    search_help_text = '可按用户账号或抖音号搜索'
    list_select_related = ('owner',)


@admin.register(UserSecurityEvent)
class UserSecurityEventAdmin(CreatorAdminMixin, admin.ModelAdmin):
    list_display = ('event', 'username', 'user', 'ip_address', 'created_at')
    list_filter = ('event', 'created_at')
    search_fields = ('username', 'user__email', 'ip_address')
    search_help_text = '可按账号、邮箱或 IP 地址搜索'
    readonly_fields = ('user', 'username', 'event', 'ip_address', 'details', 'created_at')
    date_hierarchy = 'created_at'
    list_select_related = ('user',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
