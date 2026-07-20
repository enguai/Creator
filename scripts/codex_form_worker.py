"""Codex Worker for Creator form automation.

This process is intended to run on a Windows machine that has Codex, Microsoft
Excel, and the `expense-procurement-forms` skill available. The public Django
site can run on Linux/Aliyun; it only stores uploaded files and exposes a small
Worker API. This script polls that API, downloads a job bundle, asks Codex to
run the skill, then uploads the generated workbook back to Django.

Environment variables:

CREATOR_SERVER_URL              e.g. http://120.79.5.18
FORM_AUTOMATION_WORKER_TOKEN    shared secret configured on Django
CODEX_BIN                       codex executable, defaults to "codex"
CODEX_MODEL                     optional Codex model override
CODEX_SANDBOX                   defaults to danger-full-access
CODEX_APPROVAL_POLICY           defaults to never
CODEX_WORKER_ROOT               local working dir, defaults to .codex-form-worker
CODEX_WORKER_POLL_SECONDS       defaults to 10
CODEX_WORKER_TIMEOUT_SECONDS    defaults to 1800
CODEX_WORKER_HEARTBEAT_SECONDS  defaults to 30
CODEX_WORKER_LOCAL_RETENTION_DAYS defaults to 7
CODEX_WORKER_MIN_FREE_GB        defaults to 2
CODEX_WORKER_ALLOW_MULTIPLE     set to 1 only when parallel local Workers are intended
CODEX_WORKER_RUN_ONCE           set to 1 for one poll cycle
"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class WorkerError(RuntimeError):
    pass


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def required_env(name: str) -> str:
    value = env(name)
    if not value:
        raise WorkerError(f"缺少环境变量：{name}")
    return value


def server_url() -> str:
    return required_env("CREATOR_SERVER_URL").rstrip("/")


def worker_token() -> str:
    value = required_env("FORM_AUTOMATION_WORKER_TOKEN")
    if value.startswith("FORM_AUTOMATION_WORKER_TOKEN="):
        value = value.split("=", 1)[1].strip()
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise WorkerError(
            "FORM_AUTOMATION_WORKER_TOKEN 里包含中文或其他非 HTTP Header 字符。"
            "请只填写服务器 /etc/creator.env 里等号后面的 token，不要填写说明文字。"
        ) from exc
    return value


def api_url(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{server_url()}/{path.lstrip('/')}"


def worker_instance_id() -> str:
    return f"{env('COMPUTERNAME', 'windows-worker')}:{os.getpid()}"


def worker_root() -> Path:
    return Path(env("CODEX_WORKER_ROOT", ".codex-form-worker")).resolve()


def request_json(
    path: str,
    method: str = "GET",
    payload: dict | None = None,
    *,
    timeout: int = 60,
) -> dict:
    body = None
    headers = {
        "X-Creator-Worker-Token": worker_token(),
        "X-Creator-Worker-Id": worker_instance_id(),
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(api_url(path), data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise WorkerError(f"HTTP {exc.code}: {detail[:1000]}") from exc


def post_multipart(path: str, fields: dict[str, str], files: dict[str, Path]) -> dict:
    boundary = f"----creator-worker-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    for name, path_obj in files.items():
        filename = path_obj.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(path_obj.read_bytes())
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)
    request = urllib.request.Request(
        api_url(path),
        data=body,
        headers={
            "X-Creator-Worker-Token": worker_token(),
            "X-Creator-Worker-Id": worker_instance_id(),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise WorkerError(f"HTTP {exc.code}: {detail[:1000]}") from exc


class WorkerInstanceLock:
    def __init__(self, root: Path):
        self.path = root / ".worker.lock"
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise WorkerError(
                f"已有 Worker 使用目录 {self.path.parent}。请保留一个进程，或明确设置 CODEX_WORKER_ALLOW_MULTIPLE=1。"
            ) from exc
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        if not self.handle:
            return
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class HeartbeatReporter:
    def __init__(self, job_payload: dict):
        self.url = job_payload.get("heartbeat_url", "")
        self.claim_token = job_payload.get("claim_token", "")
        self.interval = max(10, int(env("CODEX_WORKER_HEARTBEAT_SECONDS", "30")))
        self.progress = int(job_payload.get("job", {}).get("progress", 5))
        self.message = job_payload.get("job", {}).get("progress_message", "Worker 已领取任务")
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._claim_error = ""

    def _send(self) -> None:
        if not self.url or not self.claim_token:
            return
        with self._lock:
            payload = {
                "claim_token": self.claim_token,
                "worker_id": worker_instance_id(),
                "progress": self.progress,
                "message": self.message,
            }
        try:
            request_json(self.url, method="POST", payload=payload, timeout=20)
        except WorkerError as exc:
            if "HTTP 409" in str(exc):
                self._claim_error = str(exc)
            raise

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self._send()
            except Exception as exc:  # noqa: BLE001 - temporary network errors should not kill the Worker
                print(f"[worker] 心跳上报失败：{exc}", file=sys.stderr)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="worker-heartbeat", daemon=True)
        self._thread.start()

    def update(self, progress: int, message: str) -> None:
        with self._lock:
            self.progress = max(self.progress, min(99, max(1, int(progress))))
            self.message = str(message)[:200]
        try:
            self._send()
        except Exception as exc:  # noqa: BLE001 - the background heartbeat keeps retrying
            print(f"[worker] 进度上报失败：{exc}", file=sys.stderr)
        self.ensure_active()

    def ensure_active(self) -> None:
        if self._claim_error:
            raise WorkerError("任务租约已失效，停止处理当前任务副本。")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)


def ensure_free_disk_space(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    try:
        minimum_gb = max(0.1, float(env("CODEX_WORKER_MIN_FREE_GB", "2")))
    except ValueError:
        minimum_gb = 2.0
    free_gb = shutil.disk_usage(root).free / 1024 / 1024 / 1024
    if free_gb < minimum_gb:
        raise WorkerError(
            f"Worker 磁盘剩余 {free_gb:.2f} GB，低于安全值 {minimum_gb:.2f} GB，暂停领取新任务。"
        )


def cleanup_local_job_cache(root: Path) -> int:
    try:
        retention_days = max(1, int(env("CODEX_WORKER_LOCAL_RETENTION_DAYS", "7")))
    except ValueError:
        retention_days = 7
    cutoff = time.time() - retention_days * 86400
    removed = 0

    for category in ("form-automation", "payroll"):
        category_root = root / category
        if not category_root.exists():
            continue
        for job_dir in category_root.iterdir():
            if not job_dir.is_dir():
                continue
            try:
                uuid.UUID(job_dir.name)
                latest_mtime = max(
                    (path.stat().st_mtime for path in [job_dir, *job_dir.rglob("*")]),
                    default=job_dir.stat().st_mtime,
                )
                if latest_mtime < cutoff:
                    shutil.rmtree(job_dir)
                    removed += 1
            except (OSError, ValueError) as exc:
                print(f"[worker] 跳过本地缓存清理 {job_dir}：{exc}", file=sys.stderr)
    return removed


def prepare_job_directory(category: str, job_id: str) -> Path:
    normalized_id = str(uuid.UUID(job_id))
    category_root = (worker_root() / category).resolve()
    job_dir = (category_root / normalized_id).resolve()
    if job_dir.parent != category_root:
        raise WorkerError("任务目录不在 Worker 根目录内，已拒绝处理。")
    if job_dir.exists():
        shutil.rmtree(job_dir)
    (job_dir / "input").mkdir(parents=True, exist_ok=True)
    return job_dir


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or f"file-{uuid.uuid4().hex}"


def download_asset(asset: dict, job_dir: Path) -> Path:
    group = safe_filename(asset["group"])
    target_dir = job_dir / "input" / group
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_filename(asset["name"])
    request = urllib.request.Request(
        api_url(asset["download_url"]),
        headers={
            "X-Creator-Worker-Token": worker_token(),
            "X-Creator-Worker-Id": worker_instance_id(),
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=180) as response, target.open("wb") as target_file:
        shutil.copyfileobj(response, target_file, length=1024 * 1024)
    return target


def build_prompt(job_payload: dict, local_assets: list[tuple[dict, Path]], output_path: Path) -> str:
    job = job_payload["job"]
    form_type_label = "费用报销表" if job["form_type"] == "expense" else "采购申请表"
    grouped: dict[str, list[str]] = {}
    for asset, path_obj in local_assets:
        grouped.setdefault(asset["group"], []).append(str(path_obj))

    materials = "\n".join(
        f"- {group}:\n" + "\n".join(f"  - {item}" for item in items)
        for group, items in grouped.items()
    )

    return f"""你是 Creator 网站后台的 Codex Worker。请严格使用 $expense-procurement-forms 技能完成本任务。

任务类型：{form_type_label}
任务编号：{job['id']}

要求：
1. 必须读取 expense-procurement-forms 的 SKILL.md 和 references/rules.md，并按该 skill 的质量门槛生成。
2. 不要向用户追问，不要等待交互；如果材料不足，请尽最大可能基于可见证据处理，无法确定的字段按 skill 规则处理或在最终结果中说明。
3. 费用报销表必须把发票原文件作为 Excel 附件对象嵌入，不要用发票截图冒充原始发票文件。
4. 采购申请表必须保留第二张“采购三方比价表”。
5. 最终只需要生成一个 xlsx 文件，必须保存到下面这个绝对路径：
   {output_path}
6. 生成完成后，请检查文件确实存在，并在最终回答中简短说明成功或失败。

材料文件：
{materials}
"""


PAYROLL_ROOM_LABELS = {
    "z4-neck": "Z4 颈膜直播间",
    "z2-eye": "Z2 眼膜直播间",
    "z3-polish": "Z3 抛光直播间",
}


def build_payroll_prompt(job_payload: dict, local_assets: list[tuple[dict, Path]], output_path: Path) -> str:
    job = job_payload["job"]
    grouped: dict[str, list[str]] = {}
    for asset, path_obj in local_assets:
        grouped.setdefault(asset["group"], []).append(str(path_obj))

    materials = "\n".join(
        f"- {group}:\n" + "\n".join(f"  - {item}" for item in items)
        for group, items in grouped.items()
    )
    period = f"{job.get('week_start') or '未填写'} 至 {job.get('week_end') or '未填写'}"
    room = PAYROLL_ROOM_LABELS.get(job["room_type"], job["room_type"])

    return f"""你是 Creator 网站后台的 Codex Worker。请严格使用 $live-payroll skill 完成本次兼职薪资计算。
任务编号：{job['id']}
选择直播间：{room}（规则配置标识：{job['room_type']}）
薪资计算周期：{period}

必须遵守：
1. 先读取 live-payroll 的 SKILL.md、references/rules.md 和 references/schedule-json.md；按对应直播间规则处理，不得使用测试工资表或简化占位表。
2. 读取三张排班表和主播数据，将可确认的排班整理为 schedule JSON，再运行 live-payroll 的 generate_payroll.mjs 和 verify_payroll.mjs。
3. 不向网站用户追问，也不等待交互；仅以可见材料为依据，不能确认的信息不得编造。若材料不足以安全计算，停止生成并在最终消息中清楚说明缺失或歧义原因。
4. 必须保留对应直播间模板中的工作表、合并单元格、公式、格式、支付关联与统计模块；生成新的 .xlsx，不得修改 skill 的源模板。
5. 生成后必须执行校验并完成最终视觉检查。
6. 最终只生成一个 .xlsx 文件，保存到以下绝对路径：
   {output_path}
7. 完成后确认文件存在，并在最终消息简短说明生成与校验结果。

上传材料：
{materials}
"""


def resolve_codex_command() -> list[str]:
    """Find a usable Codex executable even after the desktop app updates it."""
    configured = env("CODEX_BIN")
    if configured:
        command = shlex.split(configured, posix=os.name != "nt")
        if command and (Path(command[0]).is_file() or shutil.which(command[0])):
            return command

    path_command = shutil.which("codex")
    if path_command:
        return [path_command]

    codex_bin_root = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    candidates = sorted(
        codex_bin_root.glob("*/codex.exe"),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return [str(candidates[0])]

    raise WorkerError(
        "未找到可执行的 Codex CLI。请打开 Codex 桌面应用完成安装，或设置有效的 CODEX_BIN。"
    )


def codex_command(prompt_path: Path, output_path: Path, image_paths: list[Path], final_message_path: Path) -> list[str]:
    command = resolve_codex_command()

    help_text = ""
    try:
        help_result = subprocess.run(
            command + ["exec", "--help"],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
        )
        help_text = f"{help_result.stdout}\n{help_result.stderr}"
    except Exception:
        help_text = ""

    args = command + [
        "exec",
        "--cd",
        str(prompt_path.parent),
        "--skip-git-repo-check",
        "--output-last-message",
        str(final_message_path),
    ]
    approval_policy = env("CODEX_APPROVAL_POLICY", "never")
    sandbox_mode = env("CODEX_SANDBOX", "danger-full-access")
    if "--ask-for-approval" in help_text:
        args.extend(["--sandbox", sandbox_mode, "--ask-for-approval", approval_policy])
    elif env("CODEX_BYPASS_APPROVALS_AND_SANDBOX", "1") != "0" and "--dangerously-bypass-approvals-and-sandbox" in help_text:
        args.append("--dangerously-bypass-approvals-and-sandbox")
    elif "--sandbox" in help_text:
        args.extend(["--sandbox", sandbox_mode])

    model = env("CODEX_MODEL")
    if model:
        args.extend(["--model", model])

    for image_path in image_paths:
        args.extend(["--image", str(image_path)])

    return args


def normalize_generated_workbook(workbook_path: Path, job_dir: Path) -> dict:
    """Normalize fonts/formulas through Excel COM so embedded OLE files survive."""

    if os.name != "nt":
        return {"workbook_normalized": False, "normalize_reason": "Excel COM only runs on Windows"}

    script_path = job_dir / "normalize_workbook.ps1"
    script_path.write_text(
        r'''
param(
  [Parameter(Mandatory=$true)][string]$WorkbookPath
)
$ErrorActionPreference = "Stop"
$excel = $null
$workbook = $null
try {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $workbook = $excel.Workbooks.Open($WorkbookPath)
  $worksheet = $workbook.Worksheets.Item(1)
  $usedRange = $worksheet.UsedRange
  $lastRow = $usedRange.Row + $usedRange.Rows.Count - 1
  $totalRow = 0
  for ($row = $lastRow; $row -ge 5; $row--) {
    $text = [string]$worksheet.Cells.Item($row, 1).Text
    if ($text -like "*总合计*" -or $text -like "*合计*") {
      $totalRow = $row
      break
    }
  }
  if ($totalRow -eq 0) {
    throw "Workbook validation failed: total row was not found."
  }

  $lastDetailRow = $totalRow - 1
  if ($lastDetailRow -ge 5) {
    $detailRange = $worksheet.Range("A5:M$lastDetailRow")
    $detailRange.Font.Color = 0
    $detailRange.Font.Bold = $false
    $detailRange.Font.Size = 12
  }

  if ($totalRow -ge 5) {
    $totalRange = $worksheet.Range("A$totalRow:M$totalRow")
    $totalRange.Font.Color = 0
    $totalRange.Font.Bold = $true
    $totalRange.Font.Size = 16

    if ($lastDetailRow -ge 5) {
      $formulaCell = $worksheet.Cells.Item($totalRow, 9)
      if ($formulaCell.MergeCells) {
        $formulaCell = $formulaCell.MergeArea.Cells.Item(1, 1)
      }
      $formulaCell.Formula = "=SUM(I5:I$lastDetailRow)"
    }
  }

  $workbook.Save()
  [pscustomobject]@{
    workbook_normalized = $true
    total_row = $totalRow
    last_detail_row = $lastDetailRow
  } | ConvertTo-Json -Compress
}
finally {
  if ($workbook -ne $null) { $workbook.Close($true) | Out-Null }
  if ($excel -ne $null) {
    $excel.Quit() | Out-Null
    [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
  }
}
'''.strip(),
        encoding="utf-8-sig",
    )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            str(workbook_path),
        ],
        cwd=job_dir,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=120,
    )
    if completed.returncode != 0:
        return {
            "workbook_normalized": False,
            "normalize_error": (completed.stderr or completed.stdout or "")[-2000:],
        }
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"workbook_normalized": True, "normalize_output": completed.stdout[-1000:]}


def run_codex(
    job_dir: Path,
    prompt: str,
    local_assets: list[tuple[dict, Path]],
    reporter: HeartbeatReporter,
    *,
    normalize_workbook: bool,
) -> tuple[Path, dict]:
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "result.xlsx"
    prompt_path = job_dir / "task.md"
    final_message_path = job_dir / "codex-final-message.md"
    stdout_path = job_dir / "codex-stdout.log"
    stderr_path = job_dir / "codex-stderr.log"
    prompt_path.write_text(prompt, encoding="utf-8")

    image_paths = [
        path_obj
        for _asset, path_obj in local_assets
        if path_obj.suffix.lower() in IMAGE_EXTENSIONS
    ]
    args = codex_command(prompt_path, output_path, image_paths, final_message_path)
    timeout = int(env("CODEX_WORKER_TIMEOUT_SECONDS", "1800"))
    early_complete_seconds = int(env("CODEX_WORKER_EARLY_COMPLETE_SECONDS", "0"))
    started = time.time()
    early_completed = False
    last_output_size = -1
    output_stable_since: float | None = None
    last_estimated_progress = 35
    output_reported = False
    reporter.update(35, "Codex 正在生成文件")
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
        process = subprocess.Popen(
            args,
            cwd=job_dir,
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.stdin:
            process.stdin.write("请读取并执行 task.md 中的后台任务。")
            process.stdin.close()

        while True:
            returncode = process.poll()
            if returncode is not None:
                break

            elapsed = time.time() - started
            if elapsed > timeout:
                process.kill()
                process.wait(timeout=30)
                raise WorkerError(f"Codex 执行超时，超过 {timeout} 秒。")

            estimated_progress = min(75, 35 + int((elapsed / timeout) * 40))
            if estimated_progress >= last_estimated_progress + 2:
                reporter.update(estimated_progress, "Codex 正在生成文件")
                last_estimated_progress = estimated_progress

            if early_complete_seconds > 0 and output_path.exists() and output_path.stat().st_size > 0:
                if not output_reported:
                    reporter.update(80, "已生成结果文件，正在完成校验")
                    output_reported = True
                current_size = output_path.stat().st_size
                if current_size == last_output_size:
                    if output_stable_since is None:
                        output_stable_since = time.time()
                    elif time.time() - output_stable_since >= early_complete_seconds:
                        early_completed = True
                        process.terminate()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=30)
                        break
                else:
                    last_output_size = current_size
                    output_stable_since = time.time()

            time.sleep(2)

    stderr_tail = stderr_path.read_text(encoding="utf-8", errors="ignore")[-2000:] if stderr_path.exists() else ""
    returncode = process.returncode if process.returncode is not None else 0
    if returncode != 0 and not early_completed:
        raise WorkerError(
            f"Codex 执行失败，退出码 {returncode}。"
            f"stderr: {stderr_tail}"
        )
    if not output_path.exists():
        raise WorkerError(
            "Codex 已结束，但没有生成指定的 output/result.xlsx。"
            f"最终消息：{final_message_path.read_text(encoding='utf-8', errors='ignore')[-2000:] if final_message_path.exists() else ''}"
        )

    reporter.update(84, "正在检查生成结果")
    if normalize_workbook:
        reporter.update(87, "正在整理工作簿格式和公式")
    normalize_summary = (
        normalize_generated_workbook(output_path, job_dir)
        if normalize_workbook
        else {"workbook_normalized": False, "normalize_reason": "preserved live-payroll workbook formatting"}
    )
    reporter.update(92, "结果文件已就绪，准备上传")

    summary = {
        "mode": "codex-skill-worker",
        "worker": env("COMPUTERNAME", "windows-worker"),
        "duration_seconds": round(time.time() - started, 2),
        "early_completed": early_completed,
        **normalize_summary,
        "codex_final_message": (
            final_message_path.read_text(encoding="utf-8", errors="ignore")[-3000:]
            if final_message_path.exists()
            else ""
        ),
    }
    return output_path, summary


def fail_job(job_payload: dict, message: str, summary: dict | None = None) -> None:
    payload = {
        "error_message": message[:5000],
        "summary": summary or {},
    }
    if job_payload.get("claim_token"):
        payload["claim_token"] = job_payload["claim_token"]
    request_json(
        job_payload["fail_url"],
        method="POST",
        payload=payload,
    )


def complete_job(job_payload: dict, result_path: Path, summary: dict) -> None:
    complete_url = job_payload["complete_url"]
    fields = {"summary": json.dumps(summary, ensure_ascii=False)}
    if job_payload.get("claim_token"):
        fields["claim_token"] = job_payload["claim_token"]
    post_multipart(
        complete_url,
        fields=fields,
        files={"result_file": result_path},
    )


def download_job_assets(
    job_payload: dict,
    job_dir: Path,
    reporter: HeartbeatReporter,
) -> list[tuple[dict, Path]]:
    assets = job_payload["assets"]
    reporter.update(10, "正在下载任务文件")
    local_assets = []
    total = max(1, len(assets))
    for index, asset in enumerate(assets, start=1):
        local_assets.append((asset, download_asset(asset, job_dir)))
        reporter.update(10 + int(15 * index / total), f"正在下载任务文件（{index}/{len(assets)}）")
    return local_assets


def process_form_job(job_payload: dict, reporter: HeartbeatReporter) -> None:
    job = job_payload["job"]
    job_dir = prepare_job_directory("form-automation", job["id"])

    print(f"[worker] 领取报销表格任务 {job['id']} ({job['form_type']})")
    local_assets = download_job_assets(job_payload, job_dir, reporter)
    output_path = job_dir / "output" / "result.xlsx"
    reporter.update(30, "任务文件已就绪，正在准备 Codex")
    prompt = build_prompt(job_payload, local_assets, output_path)

    result_path, summary = run_codex(job_dir, prompt, local_assets, reporter, normalize_workbook=True)
    reporter.update(96, "正在上传结果文件")
    reporter.stop()
    reporter.ensure_active()
    complete_job(job_payload, result_path, summary)
    os.utime(job_dir, None)
    print(f"[worker] 报销表格任务完成 {job['id']} -> {result_path}")


def process_payroll_job(job_payload: dict, reporter: HeartbeatReporter) -> None:
    job = job_payload["job"]
    job_dir = prepare_job_directory("payroll", job["id"])

    print(f"[worker] 领取兼职薪资任务 {job['id']} ({job['room_type']})")
    local_assets = download_job_assets(job_payload, job_dir, reporter)
    output_path = job_dir / "output" / "result.xlsx"
    reporter.update(30, "任务文件已就绪，正在准备 Codex")
    prompt = build_payroll_prompt(job_payload, local_assets, output_path)

    result_path, summary = run_codex(job_dir, prompt, local_assets, reporter, normalize_workbook=False)
    summary.update({"skill": "live-payroll", "room_type": job["room_type"]})
    reporter.update(96, "正在上传结果文件")
    reporter.stop()
    reporter.ensure_active()
    complete_job(job_payload, result_path, summary)
    os.utime(job_dir, None)
    print(f"[worker] 兼职薪资任务完成 {job['id']} -> {result_path}")


def poll_queue(endpoint: str, processor, label: str) -> bool:
    payload = request_json(
        endpoint,
        method="POST",
        payload={"worker_id": worker_instance_id()},
    )
    if not payload.get("job"):
        return False

    reporter = HeartbeatReporter(payload)
    reporter.start()
    try:
        processor(payload, reporter)
    except Exception as exc:  # noqa: BLE001 - worker must report every failure
        reporter.stop()
        message = f"{exc}\n{traceback.format_exc()}"
        print(f"[worker] {label}失败：{message}", file=sys.stderr)
        try:
            fail_job(payload, message, {"mode": "codex-skill-worker"})
        except Exception as report_exc:  # noqa: BLE001
            print(f"[worker] {label}失败原因回传失败：{report_exc}", file=sys.stderr)
    finally:
        reporter.stop()
    return True


QUEUE_DEFINITIONS = (
    ("/api/forms/worker/jobs/next/", process_form_job, "报销表格任务"),
    ("/api/payroll/worker/jobs/next/", process_payroll_job, "兼职薪资任务"),
)
queue_cursor = 0


def poll_once() -> bool:
    global queue_cursor
    for offset in range(len(QUEUE_DEFINITIONS)):
        index = (queue_cursor + offset) % len(QUEUE_DEFINITIONS)
        endpoint, processor, label = QUEUE_DEFINITIONS[index]
        if poll_queue(endpoint, processor, label):
            queue_cursor = (index + 1) % len(QUEUE_DEFINITIONS)
            return True
    return False


def run_worker_loop(root: Path) -> int:
    poll_seconds = int(env("CODEX_WORKER_POLL_SECONDS", "10"))
    run_once = env("CODEX_WORKER_RUN_ONCE") == "1"
    last_cleanup_at = 0.0
    print("[worker] Creator Codex Automation Worker started.")
    print(f"[worker] server={server_url()}")
    print(f"[worker] id={worker_instance_id()}")
    print(f"[worker] root={root}")

    while True:
        try:
            ensure_free_disk_space(root)
            if time.time() - last_cleanup_at >= 21600:
                removed = cleanup_local_job_cache(root)
                if removed:
                    print(f"[worker] 已清理 {removed} 个过期本地任务缓存。")
                last_cleanup_at = time.time()
            got_job = poll_once()
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 轮询失败：{exc}", file=sys.stderr)
            got_job = False
            if run_once:
                return 1
            time.sleep(max(30, poll_seconds))
            continue
        if run_once:
            return 0
        if not got_job:
            time.sleep(poll_seconds)


def main() -> int:
    root = worker_root()
    root.mkdir(parents=True, exist_ok=True)
    if env("CODEX_WORKER_ALLOW_MULTIPLE") == "1":
        return run_worker_loop(root)
    with WorkerInstanceLock(root):
        return run_worker_loop(root)


if __name__ == "__main__":
    raise SystemExit(main())
