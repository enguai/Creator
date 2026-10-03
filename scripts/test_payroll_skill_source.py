import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import codex_form_worker as worker


class PayrollSkillSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill = self.root / 'live-payroll' / 'SKILL.md'
        self.skill.parent.mkdir()
        self.skill.write_text('Current payroll rules', encoding='utf-8')
        self.env = patch.dict(worker.os.environ, {'CREATOR_PAYROLL_SKILL_PATH': str(self.skill)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_explicit_source_and_missing_source_fail_closed(self):
        self.assertEqual(worker.payroll_skill_path(), self.skill.resolve())
        self.skill.unlink()
        with self.assertRaises(worker.WorkerError):
            worker.payroll_skill_path()

    def test_empty_skill_rejected(self):
        self.skill.write_text('', encoding='utf-8')
        with self.assertRaises(worker.WorkerError):
            worker.payroll_skill_path()

    def test_default_shared_project01_skill(self):
        with patch.dict(worker.os.environ, {'CREATOR_PAYROLL_SKILL_PATH': ''}), patch.object(worker.Path, 'home', return_value=self.root):
            default = self.root / '.codex/skills/live-payroll/SKILL.md'
            default.parent.mkdir(parents=True)
            default.write_text('Shared rules', encoding='utf-8')
            self.assertEqual(worker.payroll_skill_path(), default.resolve())

    def test_all_rooms_reference_one_source_without_duplicate_business_rules(self):
        for room in worker.PAYROLL_ROOM_LABELS:
            prompt = worker.build_payroll_prompt({'job': {'id': 'test', 'room_type': room}}, [], self.root / 'result.xlsx')
            self.assertIn(self.skill.resolve().as_posix(), prompt)
            self.assertIn(room, prompt)
            self.assertNotIn('未列出人员继续沿用', prompt)
            self.assertNotIn('若材料不足以安全计算，停止生成', prompt)
            self.assertNotIn('generate_z5_payroll.mjs', prompt)
            self.assertIn('不得回写共享 skill', prompt)

    def test_each_job_rereads_source_and_waits_for_validation(self):
        job_dir = self.root / 'task'
        job_dir.mkdir()
        payload = {'job': {'id': 'test', 'room_type': 'z3-polish'}}
        reporter = Mock()
        with patch.object(worker, 'prepare_job_directory', return_value=job_dir), \
             patch.object(worker, 'download_job_assets', return_value=[]), \
             patch.object(worker, 'run_codex', side_effect=lambda *a, **kw: (kw['output_path'], {})) as run, \
             patch.object(worker, 'complete_job') as complete:
            worker.process_payroll_job(payload, reporter)
            first = complete.call_args.args[2]['skill_entry_sha256']
            self.skill.write_text('Updated Project01 rules', encoding='utf-8')
            worker.process_payroll_job(payload, reporter)
            latest = complete.call_args.args[2]
            self.assertNotEqual(first, latest['skill_entry_sha256'])
            self.assertEqual(latest['skill_entry_sha256'], hashlib.sha256(self.skill.read_bytes()).hexdigest())
            self.assertEqual(latest['skill_source_path'], str(self.skill.resolve()))
            self.assertFalse(run.call_args.kwargs['allow_early_completion'])
            self.assertFalse(run.call_args.kwargs['normalize_workbook'])


if __name__ == '__main__':
    unittest.main()
