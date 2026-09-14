from django.db import migrations


def seed(apps, schema_editor):
    Category = apps.get_model('core', 'KnowledgeCategory')
    for order, name in enumerate(['搭建与设备', '开播与执行', '产品与物料', '突发问题', '平台规则', '岗位教程']):
        Category.objects.get_or_create(name=name, parent=None, defaults={'order': order})
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    content_type, _ = ContentType.objects.get_or_create(app_label='core', model='knowledgerevision')
    permissions = {}
    for action, label in [('view', '查看'), ('add', '新增'), ('change', '修改'), ('delete', '删除')]:
        permissions[action], _ = Permission.objects.get_or_create(
            content_type=content_type, codename=f'{action}_knowledgerevision',
            defaults={'name': f'{label}教程与审核'})
    reviewer, _ = Permission.objects.get_or_create(content_type=content_type, codename='review_knowledge',
                                                  defaults={'name': '审核、发布及停用知识内容'})
    editor_group, _ = Group.objects.get_or_create(name='知识编辑')
    reviewer_group, _ = Group.objects.get_or_create(name='知识审核')
    editor_group.permissions.add(*permissions.values())
    reviewer_group.permissions.add(*permissions.values(), reviewer)
    category_type, _ = ContentType.objects.get_or_create(app_label='core', model='knowledgecategory')
    permission, _ = Permission.objects.get_or_create(content_type=category_type, codename='view_knowledgecategory',
                                                    defaults={'name': '查看知识分类'})
    editor_group.permissions.add(permission)
    reviewer_group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [('core', '0015_knowledge_center')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
