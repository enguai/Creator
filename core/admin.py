from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import (
    DouyinMonitorConfig,
    DouyinMonitorSession,
    FormAutomationAsset,
    FormAutomationJob,
    PayrollJob,
    Profile,
    UserSecurityEvent,
)


class CreatorAdminMixin:
    list_per_page = 25
    show_full_result_count = False
    save_on_top = True


@admin.register(Profile)
class ProfileAdmin(CreatorAdminMixin, admin.ModelAdmin):
    list_display = ('nickname', 'user')
    search_fields = ('nickname', 'user__username', 'user__email')
    search_help_text = '可按昵称、账号或邮箱搜索'
    list_select_related = ('user',)


class ProfileInline(admin.StackedInline):
    model = Profile
    extra = 0
    can_delete = False
    verbose_name_plural = '用户资料'


admin.site.unregister(User)


@admin.register(User)
class CreatorUserAdmin(CreatorAdminMixin, UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_active', 'is_staff', 'date_joined', 'last_login')
    list_filter = ('is_active', 'is_staff', 'is_superuser', 'date_joined', 'last_login')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    search_help_text = '可按账号、邮箱、姓名搜索'
    inlines = (ProfileInline,)


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
        return False
