from io import BytesIO

from django.core.files.base import ContentFile
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


FILE_LABELS = (
    ('host_schedule', '主播排班表'),
    ('controller_schedule', '场控排班表'),
    ('trial_schedule', '试播间排班表'),
    ('host_data', '主播数据'),
)


def _file_summary(job, field_name):
    file_field = getattr(job, field_name)
    return {
        'name': file_field.name.split('/')[-1] if file_field else '',
        'size': file_field.size if file_field else 0,
    }


def _payroll_period(job):
    if job.week_start and job.week_end:
        return f'{job.week_start.isoformat()} - {job.week_end.isoformat()}'
    if job.week_start:
        return f'{job.week_start.isoformat()} - 未填写'
    if job.week_end:
        return f'未填写 - {job.week_end.isoformat()}'
    return '未填写'


def generate_placeholder_payroll(job):
    """Generate a lightweight workbook proving the upload/download loop works.

    The real payroll engine will replace this function in the next phase.
    """

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '薪资计算测试结果'

    title_fill = PatternFill('solid', fgColor='4C2528')
    subtitle_fill = PatternFill('solid', fgColor='F1E7E5')
    white_font = Font(color='FFFFFF', bold=True, size=14)
    header_font = Font(color='4C2528', bold=True)

    sheet.merge_cells('A1:D1')
    sheet['A1'] = '造物者兼职薪资计算 - 测试文档'
    sheet['A1'].fill = title_fill
    sheet['A1'].font = white_font
    sheet['A1'].alignment = Alignment(horizontal='center', vertical='center')
    sheet.row_dimensions[1].height = 28

    metadata = [
        ('任务编号', str(job.id)),
        ('选择直播间', job.room_type),
        ('薪资计算周期', _payroll_period(job)),
        ('生成时间', timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')),
        ('当前阶段', '第一步：上传、生成测试文档、下载闭环已打通'),
    ]

    row = 3
    for label, value in metadata:
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(row=row, column=2, value=value)
        sheet.cell(row=row, column=1).font = header_font
        row += 1

    row += 1
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    sheet.cell(row=row, column=1, value='已上传文件')
    sheet.cell(row=row, column=1).fill = subtitle_fill
    sheet.cell(row=row, column=1).font = header_font
    row += 1

    headers = ['文件类型', '文件名', '文件大小 KB', '用途']
    for col, header in enumerate(headers, start=1):
        cell = sheet.cell(row=row, column=col, value=header)
        cell.font = header_font
        cell.fill = subtitle_fill
    row += 1

    usage_notes = {
        'host_schedule': '后续用于识别主播班次、时段与出勤信息',
        'controller_schedule': '后续用于识别场控班次、双岗小时等信息',
        'trial_schedule': '后续用于识别试播间人员与试播时长',
        'host_data': '后续用于读取主播直播数据、消耗、ROI 等信息',
    }

    for field_name, label in FILE_LABELS:
        summary = _file_summary(job, field_name)
        sheet.append([
            label,
            summary['name'],
            round(summary['size'] / 1024, 2),
            usage_notes[field_name],
        ])

    row = sheet.max_row + 2
    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    sheet.cell(
        row=row,
        column=1,
        value='说明：这是第一步生成的测试薪资文档，暂未接入真实薪资计算规则。下一步会把 work01 的薪资规则整理成后端计算引擎。',
    )
    sheet.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical='top')
    sheet.row_dimensions[row].height = 48

    widths = [22, 40, 16, 54]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    for row_cells in sheet.iter_rows():
        for cell in row_cells:
            cell.alignment = Alignment(
                vertical='center',
                wrap_text=True,
                horizontal=cell.alignment.horizontal,
            )

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    filename = f'creator-payroll-placeholder-{job.id}.xlsx'
    job.result_file.save(filename, ContentFile(buffer.read()), save=False)
    return job.result_file
