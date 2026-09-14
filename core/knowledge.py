import re
import unicodedata

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .knowledge_models import KnowledgeArticle, KnowledgeCategory, KnowledgeRevision


def can_review(user):
    return user.is_active and user.has_perm('core.review_knowledge')


@transaction.atomic
def transition(revision_id, user, action):
    # Lock the article as well, so two revisions cannot publish simultaneously.
    article_id = KnowledgeRevision.objects.values_list('article_id', flat=True).get(pk=revision_id)
    article = KnowledgeArticle.objects.select_for_update().get(pk=article_id)
    revision = KnowledgeRevision.objects.select_for_update().get(pk=revision_id)
    if action in ('publish', 'return', 'disable'):
        if not can_review(user):
            raise PermissionDenied
    elif not user.has_perm('core.change_knowledgerevision'):
        raise PermissionDenied

    if action == 'submit':
        if revision.status not in ('draft', 'returned'):
            raise ValidationError('只有草稿或已退回的内容可以提交审核。')
        revision.validate_publication()
        revision.status = 'pending'
        revision.review_note = ''
    elif action == 'publish':
        if revision.status != 'pending':
            raise ValidationError('请先提交审核，再审核发布。')
        revision.validate_publication()
        if article.published_revision_id:
            KnowledgeRevision.objects.filter(pk=article.published_revision_id).update(status='archived')
        revision.status = 'published'
        revision.reviewer = user
        revision.published_at = timezone.now()
        article.published_revision = revision
        article.is_active = True
        article.save(update_fields=['published_revision', 'is_active'])
    elif action == 'return':
        if revision.status != 'pending':
            raise ValidationError('只能退回待审核的内容。')
        if not revision.review_note.strip():
            raise ValidationError('请先进入教程填写并保存审核意见，再退回。')
        revision.status = 'returned'
        revision.reviewer = user
    elif action == 'disable':
        if article.published_revision_id != revision.pk or revision.status != 'published':
            raise ValidationError('只能停用当前发布的版本。')
        article.is_active = False
        article.save(update_fields=['is_active'])
        revision.status = 'disabled'
    elif action == 'clone':
        if revision.status not in ('published', 'archived', 'disabled'):
            raise ValidationError('草稿可直接编辑，无需创建新版本。')
        if article.revisions.filter(status__in=['draft', 'returned', 'pending']).exists():
            raise ValidationError('已有未完成的新版本，请先处理该版本。')
        number = article.revisions.aggregate(n=Max('version'))['n'] + 1
        revision.pk = None
        revision.version = number
        revision.status = 'draft'
        revision.author = user
        revision.reviewer = None
        revision.published_at = None
        revision.review_note = ''
    else:
        raise ValidationError('不支持的操作。')
    revision.save()
    return revision


def active_categories():
    categories = list(KnowledgeCategory.objects.all())
    enabled = {c.pk for c in categories if c.is_active}
    while True:
        invalid = {c.pk for c in categories if c.pk in enabled and c.parent_id and c.parent_id not in enabled}
        if not invalid:
            break
        enabled -= invalid
    return [c for c in categories if c.pk in enabled]


def published_revisions(categories):
    return KnowledgeRevision.objects.filter(
        article__is_active=True, article__published_revision_id=F('pk'),
        status='published', category_id__in=[c.pk for c in categories],
    ).select_related('category').order_by('-published_at', 'pk')


def normalize(value):
    return unicodedata.normalize('NFKC', value).lower().strip()


def match_score(revision, query):
    query = normalize(query)
    title, summary = normalize(revision.title), normalize(revision.summary)
    keywords = [normalize(k) for k in revision.keywords.splitlines() if k.strip()]
    text = '\n'.join([title, summary, normalize(revision.steps), normalize(revision.body), *keywords])
    if query in title:
        return 100
    if query in text:
        return 70 if query in summary else 40
    # Curated aliases match real questions without generating an answer.
    if any(len(k) >= 2 and k in query for k in keywords):
        return 30
    tokens = re.findall(r'[\w]+', query)
    if len(tokens) > 1 and all(token in text for token in tokens):
        return 20
    return 0
