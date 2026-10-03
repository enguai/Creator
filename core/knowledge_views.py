from django.db import transaction
import json

from django.contrib.auth import get_user_model
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.text import get_valid_filename
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .knowledge import active_categories, match_score, published_revisions
from .knowledge_models import (
    KnowledgeConversation,
    KnowledgeMessage,
    KnowledgeQuestionAsset,
    KnowledgeQuestionJob,
    KnowledgeRevision,
)
from .views import (
    claim_next_worker_job,
    owned_queryset,
    parse_json_body,
    request_claim_token,
    request_worker_id,
    require_worker_token,
    update_worker_heartbeat,
    worker_claim_matches,
    worker_tracking_payload,
)


def serialize(revision, detail=False):
    result = {
        'id': str(revision.article_id), 'title': revision.title, 'summary': revision.summary,
        'steps': [line.strip() for line in revision.steps.splitlines() if line.strip()],
        'category': {'id': revision.category_id, 'name': revision.category.name},
        'platform': revision.get_platform_display(), 'platform_id': revision.platform,
        'version': f'{revision.version}.0', 'updated_at': revision.published_at.isoformat(),
        'featured': revision.featured,
    }
    if detail:
        result.update(body=revision.body, tool_path=revision.tool_path)
    return result


@require_GET
def knowledge_catalog(request):
    if not request.user.is_authenticated:
        return JsonResponse({'message': '请先登录。'}, status=401)
    categories = active_categories()
    revisions = list(published_revisions(categories))
    nodes = {c.pk: {'id': c.pk, 'name': c.name, 'parent_id': c.parent_id, 'count': 0} for c in categories}
    for revision in revisions:
        category_id = revision.category_id
        while category_id in nodes:
            nodes[category_id]['count'] += 1
            category_id = nodes[category_id]['parent_id']
    return JsonResponse({'categories': list(nodes.values()),
        'common': [serialize(r) for r in revisions if r.featured][:6],
        'platforms': [{'id': p, 'name': label} for p, label in KnowledgeRevision.PLATFORMS]})


@require_GET
def knowledge_list(request):
    if not request.user.is_authenticated:
        return JsonResponse({'message': '请先登录。'}, status=401)
    query = request.GET.get('q', '').strip()[:200]
    categories = active_categories()
    selected = request.GET.get('category', '')
    if selected:
        try:
            ids = {int(selected)}
        except ValueError:
            return JsonResponse({'message': '分类无效。'}, status=400)
        while True:
            children = {c.pk for c in categories if c.parent_id in ids}
            if children <= ids:
                break
            ids |= children
        categories = [c for c in categories if c.pk in ids]
    revisions = published_revisions(categories)
    platform = request.GET.get('platform', '')
    if platform:
        revisions = revisions.filter(platform__in=[platform, 'all'])
    if query:
        scored = [(match_score(r, query), r) for r in revisions]
        revisions = [r for score, r in sorted(scored, key=lambda item: item[0], reverse=True) if score]
    else:
        revisions = list(revisions)
    try:
        page = max(1, int(request.GET.get('page', '1')))
    except ValueError:
        return JsonResponse({'message': '页码无效。'}, status=400)
    count = len(revisions)
    return JsonResponse({'results': [serialize(r) for r in revisions[(page-1)*10:page*10]],
                         'count': count, 'page': page, 'pages': max(1, (count+9)//10)})


@require_GET
def knowledge_detail(request, article_id):
    if not request.user.is_authenticated:
        return JsonResponse({'message': '请先登录。'}, status=401)
    revisions = published_revisions(active_categories())
    revision = revisions.filter(article_id=article_id).first()
    if not revision:
        return JsonResponse({'message': '教程尚未发布或已停用。'}, status=404)
    result = serialize(revision, detail=True)
    result['related'] = [serialize(r) for r in revisions.filter(category_id=revision.category_id).exclude(pk=revision.pk)[:3]]
    return JsonResponse(result)


def serialize_question_job(job):
    result_file = None
    if job.result_file:
        result_file = {
            'name': job.result_file.name.rsplit('/', 1)[-1],
            'size': job.result_file.size,
            'download_url': reverse('knowledge-question-download', args=[job.id]),
        }
    return {
        'id': str(job.id),
        'question': job.question,
        'conversation_id': str(job.conversation_id) if job.conversation_id else '',
        'status': job.status,
        'answer': job.answer,
        'citations': job.citations,
        'summary': job.summary,
        'error_message': job.error_message,
        'result_file': result_file,
        'files': [
            {
                'id': asset.id,
                'name': asset.original_name,
                'size': asset.size,
                'content_type': asset.content_type,
            }
            for asset in job.assets.all()
        ],
        'created_at': job.created_at.isoformat(),
        'updated_at': job.updated_at.isoformat(),
        **worker_tracking_payload(job),
    }


def serialize_message(message):
    return {
        'id': message.id,
        'role': message.role,
        'content': message.content,
        'created_at': message.created_at.isoformat(),
    }


def serialize_conversation(conversation, *, include_messages=True):
    result = {
        'id': str(conversation.id),
        'title': conversation.title,
        'created_at': conversation.created_at.isoformat(),
        'updated_at': conversation.updated_at.isoformat(),
    }
    if include_messages:
        messages = conversation.messages.order_by('created_at', 'id')[:100]
        result['messages'] = [serialize_message(message) for message in messages]
    return result


def conversation_history(job):
    if not job.conversation_id:
        return []
    messages = list(
        job.conversation.messages.exclude(job_id=job.id)
        .order_by('-created_at', '-id')[:12]
    )
    messages.reverse()
    return [serialize_message(message) for message in messages]


@require_GET
def knowledge_conversation_list(request):
    if not request.user.is_authenticated:
        return JsonResponse({'message': '请先登录。'}, status=401)
    conversations = KnowledgeConversation.objects.filter(owner=request.user).order_by('-updated_at')[:30]
    return JsonResponse(
        {'conversations': [serialize_conversation(conversation, include_messages=False) for conversation in conversations]},
        json_dumps_params={'ensure_ascii': False},
    )


@require_GET
def knowledge_conversation_detail(request, conversation_id):
    if not request.user.is_authenticated:
        return JsonResponse({'message': '请先登录。'}, status=401)
    conversation = get_object_or_404(KnowledgeConversation.objects.filter(owner=request.user), id=conversation_id)
    return JsonResponse(serialize_conversation(conversation), json_dumps_params={'ensure_ascii': False})


@csrf_exempt
@require_POST
def create_knowledge_question(request):
    if not request.user.is_authenticated:
        return JsonResponse({'message': '请先登录。'}, status=401)
    body = parse_json_body(request) if request.content_type.startswith('application/json') else request.POST
    question = str(body.get('question') or '').strip()[:500]
    if not question:
        return JsonResponse({'message': '请输入要查询的问题。'}, status=400)

    files = request.FILES.getlist('files')
    allowed_extensions = {'.xlsx', '.xls', '.csv', '.pdf', '.docx', '.png', '.jpg', '.jpeg'}
    max_files = 10
    max_size = 50 * 1024 * 1024
    if len(files) > max_files:
        return JsonResponse({'message': f'一次最多上传 {max_files} 个文件。'}, status=400)
    invalid_files = []
    oversized_files = []
    empty_files = []
    for uploaded in files:
        suffix = '.' + uploaded.name.rsplit('.', 1)[-1].lower() if '.' in uploaded.name else ''
        if suffix not in allowed_extensions:
            invalid_files.append(uploaded.name)
        if uploaded.size == 0:
            empty_files.append(uploaded.name)
        elif uploaded.size > max_size:
            oversized_files.append(uploaded.name)
    if invalid_files:
        return JsonResponse({'message': '存在不支持的文件类型，仅支持 Excel、CSV、PDF、Word 和图片。', 'files': invalid_files}, status=400)
    if empty_files:
        return JsonResponse({'message': '不能上传空文件。', 'files': empty_files}, status=400)
    if oversized_files:
        return JsonResponse({'message': '单个文件不能超过 50MB。', 'files': oversized_files}, status=400)
    with transaction.atomic():
        # 锁定用户行，保证同一用户首次提问并发到达时只创建一个隐式对话。
        owner = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        conversation_id = str(body.get('conversation_id') or '').strip()
        if conversation_id:
            conversation = get_object_or_404(
                KnowledgeConversation.objects.select_for_update().filter(owner=owner),
                id=conversation_id,
            )
        else:
            conversation = KnowledgeConversation.objects.select_for_update().filter(
                owner=owner,
            ).order_by('-updated_at', '-created_at', '-id').first()
            if conversation is None:
                conversation = KnowledgeConversation.objects.create(owner=owner, title=question[:120])
        if KnowledgeQuestionJob.objects.filter(
            conversation=conversation,
            status__in=[KnowledgeQuestionJob.Status.PENDING, KnowledgeQuestionJob.Status.RUNNING],
        ).exists():
            return JsonResponse({'message': '这个对话仍在处理中，请等待当前回答完成。'}, status=409)
        job = KnowledgeQuestionJob.objects.create(
            owner=request.user,
            conversation=conversation,
            question=question,
        )
        KnowledgeMessage.objects.create(
            conversation=conversation,
            job=job,
            role=KnowledgeMessage.Role.USER,
            content=question,
        )
        for uploaded in files:
            KnowledgeQuestionAsset.objects.create(
                job=job,
                file=uploaded,
                original_name=uploaded.name[:255],
                size=uploaded.size,
                content_type=uploaded.content_type or '',
            )
        conversation.save(update_fields=['updated_at'])
    return JsonResponse(serialize_question_job(job), status=201, json_dumps_params={'ensure_ascii': False})


@require_GET
def get_knowledge_question(request, job_id):
    job = get_object_or_404(owned_queryset(KnowledgeQuestionJob, request), id=job_id)
    return JsonResponse(serialize_question_job(job), json_dumps_params={'ensure_ascii': False})


@require_GET
def download_knowledge_question_result(request, job_id):
    if not request.user.is_authenticated:
        return JsonResponse({'message': '请先登录。'}, status=401)
    queryset = KnowledgeQuestionJob.objects.all()
    if not request.user.is_staff:
        queryset = queryset.filter(owner=request.user)
    job = get_object_or_404(queryset, id=job_id)
    if not job.result_file:
        return JsonResponse({'message': '这个任务没有可下载的结果文件。'}, status=404)
    try:
        return FileResponse(
            job.result_file.open('rb'),
            as_attachment=True,
            filename=job.result_file.name.rsplit('/', 1)[-1],
        )
    except FileNotFoundError:
        return JsonResponse({'message': '结果文件不存在，可能已被清理。'}, status=404)


def knowledge_worker_job_payload(request, job):
    return {
        'job': serialize_question_job(job),
        'assets': [
            {
                'id': asset.id,
                'group': 'knowledge_sources',
                'label': '数据源文件',
                'name': asset.original_name,
                'size': asset.size,
                'content_type': asset.content_type,
                'download_url': request.build_absolute_uri(
                    f'/api/knowledge/worker/assets/{asset.id}/download/'
                ),
            }
            for asset in job.assets.all()
        ],
        'conversation_messages': conversation_history(job),
        'complete_url': request.build_absolute_uri(
            f'/api/knowledge/worker/jobs/{job.id}/complete/'
        ),
        'fail_url': request.build_absolute_uri(
            f'/api/knowledge/worker/jobs/{job.id}/fail/'
        ),
        'heartbeat_url': request.build_absolute_uri(
            f'/api/knowledge/worker/jobs/{job.id}/heartbeat/'
        ),
        'claim_token': str(job.claim_token),
    }


@csrf_exempt
@require_POST
def worker_next_knowledge_question(request):
    if not require_worker_token(request):
        return JsonResponse({'error': 'worker_unauthorized', 'message': 'Worker token 未配置或不正确。'}, status=403)
    job = claim_next_worker_job(KnowledgeQuestionJob, request_worker_id(request, parse_json_body(request)))
    if not job:
        return JsonResponse({'ok': True, 'job': None})
    job.summary = {**(job.summary or {}), 'mode': 'knowledge-codex-chat'}
    job.save(update_fields=['summary', 'updated_at'])
    return JsonResponse(knowledge_worker_job_payload(request, job), json_dumps_params={'ensure_ascii': False})


@csrf_exempt
@require_POST
def worker_heartbeat_knowledge_question(request, job_id):
    return update_worker_heartbeat(request, KnowledgeQuestionJob, serialize_question_job, job_id)


@require_GET
def worker_download_knowledge_asset(request, asset_id):
    if not require_worker_token(request):
        return JsonResponse({'error': 'worker_unauthorized', 'message': 'Worker token 未配置或不正确。'}, status=403)
    asset = get_object_or_404(KnowledgeQuestionAsset, id=asset_id)
    try:
        return FileResponse(asset.file.open('rb'), as_attachment=True, filename=asset.original_name)
    except FileNotFoundError:
        return JsonResponse({'error': 'asset_not_found', 'message': '数据源文件不存在。'}, status=404)


@csrf_exempt
@require_POST
def worker_complete_knowledge_question(request, job_id):
    if not require_worker_token(request):
        return JsonResponse({'error': 'worker_unauthorized', 'message': 'Worker token 未配置或不正确。'}, status=403)
    body = parse_json_body(request) if request.content_type.startswith('application/json') else request.POST
    answer = str(body.get('answer') or '').strip()
    citations = body.get('citations') if isinstance(body.get('citations'), list) else []
    if isinstance(body.get('citations'), str):
        try:
            parsed_citations = json.loads(body.get('citations'))
            citations = parsed_citations if isinstance(parsed_citations, list) else []
        except (TypeError, json.JSONDecodeError):
            citations = []
    worker_summary = body.get('summary') if isinstance(body.get('summary'), dict) else {}
    if isinstance(body.get('summary'), str):
        try:
            parsed_summary = json.loads(body.get('summary'))
            worker_summary = parsed_summary if isinstance(parsed_summary, dict) else {}
        except (TypeError, json.JSONDecodeError):
            worker_summary = {}
    result_file = request.FILES.get('result_file')
    if not answer:
        return JsonResponse({'error': 'missing_answer', 'message': '请提供 Codex 答案。'}, status=400)
    claim_token = request_claim_token(request, body)
    with transaction.atomic():
        job = get_object_or_404(KnowledgeQuestionJob.objects.select_for_update(), id=job_id)
        if job.status == KnowledgeQuestionJob.Status.SUCCESS:
            return JsonResponse(serialize_question_job(job), json_dumps_params={'ensure_ascii': False})
        if not worker_claim_matches(job, claim_token):
            return JsonResponse({'error': 'worker_claim_expired', 'message': '任务已被重新分配或已经结束，当前答案不会写入。'}, status=409)
        job.answer = answer[:20000]
        job.citations = citations[:6]
        job.summary = {
            **(job.summary or {}),
            **worker_summary,
            'backend': 'codex_worker',
            'worker_completed_at': timezone.localtime(timezone.now()).isoformat(),
        }
        update_fields = [
            'answer', 'citations', 'summary', 'status', 'progress', 'progress_message',
            'claim_token', 'lease_expires_at', 'finished_at', 'error_message', 'updated_at',
        ]
        if result_file:
            result_name = get_valid_filename(result_file.name)[:120] or 'codex-result.bin'
            job.result_file.save(result_name, result_file, save=False)
            update_fields.append('result_file')
        job.status = KnowledgeQuestionJob.Status.SUCCESS
        job.progress = 100
        job.progress_message = '处理成功'
        job.claim_token = None
        job.lease_expires_at = None
        job.finished_at = timezone.now()
        job.error_message = ''
        job.save(update_fields=update_fields)
        if job.conversation_id:
            KnowledgeMessage.objects.update_or_create(
                conversation_id=job.conversation_id,
                job=job,
                role=KnowledgeMessage.Role.ASSISTANT,
                defaults={'content': job.answer},
            )
            KnowledgeConversation.objects.filter(id=job.conversation_id).update(updated_at=timezone.now())
    return JsonResponse(serialize_question_job(job), json_dumps_params={'ensure_ascii': False})


@csrf_exempt
@require_POST
def worker_fail_knowledge_question(request, job_id):
    if not require_worker_token(request):
        return JsonResponse({'error': 'worker_unauthorized', 'message': 'Worker token 未配置或不正确。'}, status=403)
    body = parse_json_body(request)
    claim_token = request_claim_token(request, body)
    error_message = str(body.get('error_message') or 'Codex Worker 生成失败。')[:5000]
    with transaction.atomic():
        job = get_object_or_404(KnowledgeQuestionJob.objects.select_for_update(), id=job_id)
        if job.status in {KnowledgeQuestionJob.Status.SUCCESS, KnowledgeQuestionJob.Status.FAILED}:
            return JsonResponse(serialize_question_job(job), json_dumps_params={'ensure_ascii': False})
        if not worker_claim_matches(job, claim_token):
            return JsonResponse({'error': 'worker_claim_expired', 'message': '任务已被重新分配或已经结束，当前失败信息不会写入。'}, status=409)
        job.status = KnowledgeQuestionJob.Status.FAILED
        job.progress_message = '处理失败'
        job.claim_token = None
        job.lease_expires_at = None
        job.finished_at = timezone.now()
        job.error_message = error_message
        job.save(update_fields=['status', 'progress_message', 'claim_token', 'lease_expires_at', 'finished_at', 'error_message', 'updated_at'])
    return JsonResponse(serialize_question_job(job), json_dumps_params={'ensure_ascii': False})
