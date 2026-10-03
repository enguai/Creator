import json

from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .knowledge import transition
from .knowledge_models import (
    KnowledgeArticle,
    KnowledgeCategory,
    KnowledgeConversation,
    KnowledgeMessage,
    KnowledgeQuestionJob,
    KnowledgeRevision,
)


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

    @override_settings(FORM_AUTOMATION_WORKER_TOKEN='test-worker-token')
    def test_codex_question_worker_runs_as_independent_chat_and_saves_answer(self):
        self.publish()
        draft = transition(self.revision.pk, self.editor, 'clone')
        draft.title = '不应被 Codex 读取的草稿'
        draft.save(update_fields=['title'])

        response = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '麦克风没有声音怎么办'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201)
        job_id = response.json()['id']
        claim = self.client.post(
            reverse('knowledge-worker-job-next'),
            data=json.dumps({'worker_id': 'test-worker'}),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )
        self.assertEqual(claim.status_code, 200)
        payload = claim.json()
        self.assertEqual(payload['job']['id'], job_id)
        self.assertNotIn('knowledge_context', payload)

        completed = self.client.post(
            reverse('knowledge-worker-job-complete', args=[job_id]),
            data=json.dumps({
                'claim_token': payload['claim_token'],
                'answer': '请检查设备连接、输入设备和试听结果。',
                'citations': [{'id': str(self.revision.article_id), 'title': self.revision.title}],
            }),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()['status'], KnowledgeQuestionJob.Status.SUCCESS)
        self.assertEqual(self.client.get(reverse('knowledge-question-detail', args=[job_id])).json()['progress'], 100)

    @override_settings(FORM_AUTOMATION_WORKER_TOKEN='test-worker-token')
    def test_codex_question_can_return_a_downloadable_result_file(self):
        response = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '请分析这份表格并生成汇总结果'}),
            content_type='application/json',
        )
        job_id = response.json()['id']
        claim = self.client.post(
            reverse('knowledge-worker-job-next'),
            data=json.dumps({'worker_id': 'test-worker'}),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        ).json()
        completed = self.client.post(
            reverse('knowledge-worker-job-complete', args=[job_id]),
            data={
                'claim_token': claim['claim_token'],
                'answer': '已生成汇总结果。',
                'citations': '[]',
                'summary': '{"result_file_generated": true}',
                'result_file': SimpleUploadedFile('数据分析结果.xlsx', b'xlsx-result'),
            },
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )

        self.assertEqual(completed.status_code, 200)
        result = completed.json()['result_file']
        self.assertEqual(result['name'], '数据分析结果.xlsx')
        self.assertTrue(result['download_url'])
        downloaded = self.client.get(result['download_url'])
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(b''.join(downloaded.streaming_content), b'xlsx-result')

        other_user = User.objects.create_user('file-reader')
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(result['download_url']).status_code, 404)

    @override_settings(FORM_AUTOMATION_WORKER_TOKEN='test-worker-token')
    def test_codex_conversation_keeps_history_for_follow_up(self):
        first = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '第一轮问题'}),
            content_type='application/json',
        )
        self.assertEqual(first.status_code, 201)
        conversation_id = first.json()['conversation_id']
        first_id = first.json()['id']

        first_claim = self.client.post(
            reverse('knowledge-worker-job-next'),
            data=json.dumps({'worker_id': 'test-worker'}),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )
        first_payload = first_claim.json()
        self.client.post(
            reverse('knowledge-worker-job-complete', args=[first_id]),
            data=json.dumps({
                'claim_token': first_payload['claim_token'],
                'answer': '第一轮回答',
            }),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )

        second = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '继续刚才的问题', 'conversation_id': conversation_id}),
            content_type='application/json',
        )
        self.assertEqual(second.status_code, 201)
        second_id = second.json()['id']
        second_claim = self.client.post(
            reverse('knowledge-worker-job-next'),
            data=json.dumps({'worker_id': 'test-worker'}),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )
        history = second_claim.json()['conversation_messages']
        self.assertEqual(
            [(item['role'], item['content']) for item in history],
            [('user', '第一轮问题'), ('assistant', '第一轮回答')],
        )

        self.client.post(
            reverse('knowledge-worker-job-complete', args=[second_id]),
            data=json.dumps({
                'claim_token': second_claim.json()['claim_token'],
                'answer': '第二轮回答',
            }),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )
        detail = self.client.get(reverse('knowledge-conversation-detail', args=[conversation_id]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            [(item['role'], item['content']) for item in detail.json()['messages']],
            [('user', '第一轮问题'), ('assistant', '第一轮回答'),
             ('user', '继续刚才的问题'), ('assistant', '第二轮回答')],
        )

    @override_settings(FORM_AUTOMATION_WORKER_TOKEN='test-worker-token')
    def test_codex_question_reuses_implicit_conversation_without_id(self):
        first = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '请记住这个测试背景'}),
            content_type='application/json',
        )
        self.assertEqual(first.status_code, 201)
        conversation_id = first.json()['conversation_id']
        first_id = first.json()['id']

        first_claim = self.client.post(
            reverse('knowledge-worker-job-next'),
            data=json.dumps({'worker_id': 'test-worker'}),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )
        self.client.post(
            reverse('knowledge-worker-job-complete', args=[first_id]),
            data=json.dumps({
                'claim_token': first_claim.json()['claim_token'],
                'answer': '已记住测试背景。',
            }),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )

        second = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '请继续刚才的测试'}),
            content_type='application/json',
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()['conversation_id'], conversation_id)

        second_claim = self.client.post(
            reverse('knowledge-worker-job-next'),
            data=json.dumps({'worker_id': 'test-worker'}),
            content_type='application/json',
            HTTP_X_CREATOR_WORKER_TOKEN='test-worker-token',
        )
        self.assertEqual(
            [(item['role'], item['content']) for item in second_claim.json()['conversation_messages']],
            [('user', '请记住这个测试背景'), ('assistant', '已记住测试背景。')],
        )

    def test_codex_conversation_rejects_parallel_question_and_is_private(self):
        first = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '尚未完成的问题'}),
            content_type='application/json',
        )
        conversation_id = first.json()['conversation_id']
        duplicate = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '同一对话的重复提交', 'conversation_id': conversation_id}),
            content_type='application/json',
        )
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(KnowledgeQuestionJob.objects.filter(conversation_id=conversation_id).count(), 1)

        other_user = User.objects.create_user('other-reader')
        self.client.force_login(other_user)
        self.assertEqual(
            self.client.get(reverse('knowledge-conversation-detail', args=[conversation_id])).status_code,
            404,
        )
        self.assertEqual(self.client.get(reverse('knowledge-conversation-list')).json()['conversations'], [])

    def test_codex_question_requires_login(self):
        self.client.logout()
        response = self.client.post(
            reverse('knowledge-question-create'),
            data=json.dumps({'question': '测试问题'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)
