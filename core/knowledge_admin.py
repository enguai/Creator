from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .knowledge import can_review, transition
from .knowledge_models import KnowledgeArticle, KnowledgeCategory, KnowledgeRevision


@admin.register(KnowledgeCategory)
class KnowledgeCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    list_filter = ('is_active', 'parent')
    search_fields = ('name',)


@admin.register(KnowledgeRevision)
class KnowledgeRevisionAdmin(admin.ModelAdmin):
    list_display = ('title', 'version', 'category', 'platform', 'status', 'author', 'published_at')
    list_filter = ('status', 'category', 'platform', 'featured')
    search_fields = ('title', 'keywords', 'summary')
    list_select_related = ('category', 'author')
    list_per_page = 25
    save_on_top = True
    fields = ('title', 'category', 'platform', 'summary', 'steps', 'body', 'keywords',
              'featured', 'tool_path', 'version', 'status', 'author', 'review_note', 'reviewer', 'published_at')
    actions = ('submit_review', 'approve', 'return_revision', 'new_version', 'disable_revision')

    def get_readonly_fields(self, request, obj=None):
        fields = ['version', 'status', 'author', 'reviewer', 'published_at']
        if not can_review(request.user):
            fields.append('review_note')
        if obj and obj.status not in ('draft', 'returned'):
            fields.extend(f for f in self.fields if f != 'review_note')
        return tuple(set(fields))

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if change:
            current = KnowledgeRevision.objects.select_for_update().get(pk=obj.pk)
            if current.status not in ('draft', 'returned'):
                # Ignore stale edit forms after another administrator submitted/published.
                current.review_note = obj.review_note if can_review(request.user) else current.review_note
                current.save(update_fields=['review_note'])
                return
        else:
            obj.article = KnowledgeArticle.objects.create()
            obj.author = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or obj.status in ('draft', 'returned'))

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop('delete_selected', None)
        if not can_review(request.user):
            for key in ('approve', 'return_revision', 'disable_revision'):
                actions.pop(key, None)
        return actions

    def apply_action(self, request, queryset, action):
        successes = 0
        for revision in queryset:
            try:
                transition(revision.pk, request.user, action)
                successes += 1
            except ValidationError as exc:
                self.message_user(request, f'{revision.title}：{"；".join(exc.messages)}', messages.ERROR)
            except PermissionDenied:
                self.message_user(request, '没有执行此操作的权限。', messages.ERROR)
        if successes:
            self.message_user(request, f'已处理 {successes} 个版本。', messages.SUCCESS)

    @admin.action(description='提交审核')
    def submit_review(self, request, queryset):
        self.apply_action(request, queryset, 'submit')

    @admin.action(description='审核通过并发布')
    def approve(self, request, queryset):
        self.apply_action(request, queryset, 'publish')

    @admin.action(description='退回修改（先填写审核意见）')
    def return_revision(self, request, queryset):
        self.apply_action(request, queryset, 'return')

    @admin.action(description='创建新版本草稿')
    def new_version(self, request, queryset):
        self.apply_action(request, queryset, 'clone')

    @admin.action(description='停用已发布教程')
    def disable_revision(self, request, queryset):
        self.apply_action(request, queryset, 'disable')
