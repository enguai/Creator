from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .knowledge import active_categories, match_score, published_revisions
from .knowledge_models import KnowledgeRevision


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
