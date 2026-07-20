from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import FormAutomationJob, PayrollJob


class Command(BaseCommand):
    help = '删除指定天数以前已成功或失败的 Worker 任务、上传文件和结果文件。'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90, help='保留最近多少天，默认 90 天。')
        parser.add_argument('--dry-run', action='store_true', help='只显示将删除的任务，不实际删除。')

    def handle(self, *args, **options):
        days = options['days']
        if days < 1:
            raise CommandError('--days 必须大于等于 1。')

        cutoff = timezone.now() - timedelta(days=days)
        dry_run = options['dry_run']
        deleted = 0
        failed = 0

        querysets = (
            ('表格自动化', FormAutomationJob.objects.filter(
                status__in=[FormAutomationJob.Status.SUCCESS, FormAutomationJob.Status.FAILED],
                updated_at__lt=cutoff,
            ).prefetch_related('assets')),
            ('兼职薪资', PayrollJob.objects.filter(
                status__in=[PayrollJob.Status.SUCCESS, PayrollJob.Status.FAILED],
                updated_at__lt=cutoff,
            )),
        )

        for label, queryset in querysets:
            for job in queryset.iterator(chunk_size=100):
                if dry_run:
                    self.stdout.write(f'[预览] {label} {job.id} {job.status} {job.updated_at.isoformat()}')
                    deleted += 1
                    continue

                try:
                    self._delete_job_files(job)
                    with transaction.atomic():
                        job.delete()
                    deleted += 1
                except Exception as exc:  # noqa: BLE001 - continue cleaning independent jobs
                    failed += 1
                    self.stderr.write(f'[跳过] {label} {job.id}：{exc}')

        action = '将删除' if dry_run else '已删除'
        self.stdout.write(self.style.SUCCESS(f'{action} {deleted} 个历史任务；跳过 {failed} 个任务。'))

    @staticmethod
    def _delete_file(file_field):
        if file_field and file_field.name:
            file_field.storage.delete(file_field.name)

    def _delete_job_files(self, job):
        self._delete_file(job.result_file)
        if isinstance(job, FormAutomationJob):
            for asset in job.assets.all():
                self._delete_file(asset.file)
            return

        for field_name in (
            'host_schedule',
            'controller_schedule',
            'trial_schedule',
            'host_data',
        ):
            self._delete_file(getattr(job, field_name))
