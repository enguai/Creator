from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .knowledge import transition
from .knowledge_models import KnowledgeArticle, KnowledgeCategory, KnowledgeRevision


class KnowledgeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.employee = User.objects.create_user('reader')
        cls.editor = User.objects.create_user('editor', is_staff=True)
        cls.editor.groups.add(Group.objects.get(name='知识编辑'))
        cls.reviewer = User.objects.create_user('reviewer', is_staff=True)
        cls.reviewer.groups.add(Group.objects.get(name='知识审核'))
        cls.category = KnowledgeCategory.objects.create(name='测试设备')

    def setUp(self):
        self.client.force_login(self.employee)
        self.revision = KnowledgeRevision.objects.create(
            article=KnowledgeArticle.objects.create(), title='直播声音排查', category=self.category,
            summary='检查输入设备及静音设置。', steps='检查连接\n检查输入\n试听确认',
            body='测试教程正文。\n\n确认设备后进行试听。', keywords='麦克风没声音\n没有声音',
            author=self.editor, featured=True, platform='douyin')

    def publish(self, revision=None):
        revision = revision or self.revision
        transition(revision.pk, self.editor, 'submit')
        return transition(revision.pk, self.reviewer, 'publish')

    def results(self, **query):
        return self.client.get(reverse('knowledge-list'), query).json()

    def test_authentication_required(self):
        self.client.logout()
        for url in [reverse('knowledge-list'), reverse('knowledge-catalog'),
                    reverse('knowledge-detail', args=[self.revision.article_id])]:
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_unreviewed_content_never_visible(self):
        self.assertEqual(self.results()['count'], 0)
        transition(self.revision.pk, self.editor, 'submit')
        self.assertEqual(self.results()['count'], 0)
        self.assertEqual(self.client.get(reverse('knowledge-detail', args=[self.revision.article_id])).status_code, 404)

    def test_employee_and_editor_cannot_publish(self):
        transition(self.revision.pk, self.editor, 'submit')
        for user in [self.employee, self.editor]:
            with self.assertRaises(PermissionDenied):
                transition(self.revision.pk, user, 'publish')

    def test_cannot_skip_review_submission(self):
        with self.assertRaises(ValidationError):
            transition(self.revision.pk, self.reviewer, 'publish')

    def test_search_alias_and_exact_no_match(self):
        self.publish()
        self.assertEqual(self.results(q='直播声音')['count'], 1)
        self.assertEqual(self.results(q='我的麦克风没声音怎么办')['count'], 1)
        self.assertEqual(self.results(q='完全不存在的查询内容')['count'], 0)
        self.assertEqual(self.results(q='直播 试听')['count'], 1)

    def test_platform_filter(self):
        self.publish()
        self.assertEqual(self.results(platform='douyin')['count'], 1)
        self.assertEqual(self.results(platform='tmall')['count'], 0)

    def test_full_tutorial_and_metadata(self):
        self.publish()
        data = self.client.get(reverse('knowledge-detail', args=[self.revision.article_id])).json()
        self.assertEqual(data['version'], '1.0')
        self.assertEqual(len(data['steps']), 3)
        self.assertEqual(data['body'], self.revision.body)
        self.assertTrue(data['updated_at'])

    def test_new_draft_does_not_change_published_answer(self):
        self.publish()
        draft = transition(self.revision.pk, self.editor, 'clone')
        draft.summary = '新版待审核答案'
        draft.save()
        self.assertEqual(self.results()['results'][0]['summary'], self.revision.summary)
        self.publish(draft)
        data = self.results()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['summary'], '新版待审核答案')
        self.assertEqual(data['results'][0]['version'], '2.0')
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.status, 'archived')

    def test_prevent_duplicate_drafts(self):
        self.publish()
        transition(self.revision.pk, self.editor, 'clone')
        with self.assertRaises(ValidationError):
            transition(self.revision.pk, self.editor, 'clone')

    def test_disable_removes_results_common_and_detail(self):
        self.publish()
        transition(self.revision.pk, self.reviewer, 'disable')
        self.assertEqual(self.results()['count'], 0)
        self.assertEqual(self.client.get(reverse('knowledge-catalog')).json()['common'], [])
        self.assertEqual(self.client.get(reverse('knowledge-detail', args=[self.revision.article_id])).status_code, 404)

    def test_parent_disable_hides_descendants(self):
        parent = KnowledgeCategory.objects.create(name='父分类')
        self.category.parent = parent
        self.category.save()
        self.publish()
        self.assertEqual(self.results(category=parent.pk)['count'], 1)
        parent.is_active = False
        parent.save()
        self.assertEqual(self.results()['count'], 0)

    def test_category_cycle_validation(self):
        child = KnowledgeCategory.objects.create(name='子分类', parent=self.category)
        self.category.parent = child
        with self.assertRaises(ValidationError):
            self.category.full_clean()

    def test_quick_steps_need_three_to_five_lines(self):
        self.revision.steps = '只有一步'
        self.revision.save()
        with self.assertRaises(ValidationError):
            transition(self.revision.pk, self.editor, 'submit')

    def test_return_requires_reason(self):
        transition(self.revision.pk, self.editor, 'submit')
        with self.assertRaises(ValidationError):
            transition(self.revision.pk, self.reviewer, 'return')
        self.revision.review_note = '请补充操作细节'
        self.revision.save(update_fields=['review_note'])
        returned = transition(self.revision.pk, self.reviewer, 'return')
        self.assertEqual(returned.status, 'returned')

    def test_admin_locks_published_fields(self):
        revision = self.publish()
        request = RequestFactory().get('/')
        request.user = self.editor
        model_admin = admin.site._registry[KnowledgeRevision]
        self.assertIn('body', model_admin.get_readonly_fields(request, revision))
        self.assertFalse(model_admin.has_delete_permission(request, revision))
        self.assertNotIn('approve', model_admin.get_actions(request))

    def test_admin_editor_can_add_and_reviewer_can_read(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get('/admin/core/knowledgerevision/add/').status_code, 200)
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get('/admin/core/knowledgerevision/').status_code, 200)

    def test_invalid_query_parameters(self):
        self.assertEqual(self.client.get(reverse('knowledge-list'), {'category': 'bad'}).status_code, 400)
        self.assertEqual(self.client.get(reverse('knowledge-list'), {'page': 'bad'}).status_code, 400)

    def test_pagination(self):
        self.publish()
        self.assertEqual(self.results(page=2)['results'], [])
