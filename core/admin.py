from django.contrib import admin

from .models import (
    DouyinMonitorConfig,
    DouyinMonitorSession,
    FormAutomationAsset,
    FormAutomationJob,
    PayrollJob,
    Profile,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('nickname', 'user')
    search_fields = ('nickname', 'user__username', 'user__email')


@admin.register(PayrollJob)
class PayrollJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'room_type', 'status', 'progress', 'attempt_count', 'worker_id', 'created_at', 'updated_at')
    list_filter = ('status', 'room_type', 'created_at')
    search_fields = ('id', 'error_message')
    readonly_fields = ('id', 'claim_token', 'created_at', 'updated_at')


class FormAutomationAssetInline(admin.TabularInline):
    model = FormAutomationAsset
    extra = 0
    readonly_fields = ('created_at',)


@admin.register(FormAutomationJob)
class FormAutomationJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'form_type', 'status', 'progress', 'attempt_count', 'worker_id', 'created_at', 'updated_at')
    list_filter = ('status', 'form_type', 'created_at')
    search_fields = ('id', 'error_message')
    readonly_fields = ('id', 'claim_token', 'created_at', 'updated_at')
    inlines = (FormAutomationAssetInline,)


@admin.register(DouyinMonitorSession)
class DouyinMonitorSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'douyin_id', 'room_title', 'status', 'current_count', 'started_at', 'ended_at')
    list_filter = ('status', 'started_at')
    search_fields = ('id', 'douyin_id', 'room_title')
    readonly_fields = ('id', 'started_at', 'updated_at')


@admin.register(DouyinMonitorConfig)
class DouyinMonitorConfigAdmin(admin.ModelAdmin):
    list_display = ('douyin_id', 'enabled', 'mode', 'threshold', 'cooldown_enabled', 'updated_at')
    list_filter = ('enabled', 'mode', 'cooldown_enabled')
    search_fields = ('douyin_id',)
