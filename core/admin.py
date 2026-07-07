from django.contrib import admin

from .models import PayrollJob, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('nickname', 'user')
    search_fields = ('nickname', 'user__username', 'user__email')


@admin.register(PayrollJob)
class PayrollJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'room_type', 'week_start', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'room_type', 'created_at')
    search_fields = ('id', 'error_message')
    readonly_fields = ('id', 'created_at', 'updated_at')
