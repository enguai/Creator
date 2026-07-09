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
CODEX_WORKER_RUN_ONCE           set to 1 for one poll cycle
"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
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
    return required_env("FORM_AUTOMATION_WORKER_TOKEN")


def api_url(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{server_url()}/{path.lstrip('/')}"


def request_json(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = None
    headers = {
        "X-Creator-Worker-Token": worker_token(),
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(api_url(path), data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
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
        headers={"X-Creator-Worker-Token": worker_token()},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        target.write_bytes(response.read())
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


def codex_command(prompt_path: Path, output_path: Path, image_paths: list[Path], final_message_path: Path) -> list[str]:
    codex_bin = env("CODEX_BIN", "codex")
    command = shlex.split(codex_bin, posix=os.name != "nt")
    if not command:
        command = ["codex"]

    args = command + [
        "exec",
        "--cd",
        str(prompt_path.parent),
        "--sandbox",
        env("CODEX_SANDBOX", "danger-full-access"),
        "--ask-for-approval",
        env("CODEX_APPROVAL_POLICY", "never"),
        "--skip-git-repo-check",
        "--output-last-message",
        str(final_message_path),
    ]
    model = env("CODEX_MODEL")
    if model:
        args.extend(["--model", model])

    for image_path in image_paths:
        args.extend(["--image", str(image_path)])

    args.append("请读取并执行 task.md 中的后台任务。")
    return args


def run_codex(job_dir: Path, prompt: str, local_assets: list[tuple[dict, Path]]) -> tuple[Path, dict]:
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
    started = time.time()
    completed = subprocess.run(
        args,
        cwd=job_dir,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")

    if completed.returncode != 0:
        raise WorkerError(
            f"Codex 执行失败，退出码 {completed.returncode}。"
            f"stderr: {(completed.stderr or '')[-2000:]}"
        )
    if not output_path.exists():
        raise WorkerError(
            "Codex 已结束，但没有生成指定的 output/result.xlsx。"
            f"最终消息：{final_message_path.read_text(encoding='utf-8', errors='ignore')[-2000:] if final_message_path.exists() else ''}"
        )

    summary = {
        "mode": "codex-skill-worker",
        "worker": env("COMPUTERNAME", "windows-worker"),
        "duration_seconds": round(time.time() - started, 2),
        "codex_final_message": (
            final_message_path.read_text(encoding="utf-8", errors="ignore")[-3000:]
            if final_message_path.exists()
            else ""
        ),
    }
    return output_path, summary


def fail_job(job_payload: dict, message: str, summary: dict | None = None) -> None:
    job_id = job_payload.get("job", {}).get("id", "")
    path = f"/api/forms/worker/jobs/{job_id}/fail/"
    request_json(
        path,
        method="POST",
        payload={
            "error_message": message[:5000],
            "summary": summary or {},
        },
    )


def complete_job(job_payload: dict, result_path: Path, summary: dict) -> None:
    complete_url = job_payload["complete_url"]
    post_multipart(
        complete_url,
        fields={"summary": json.dumps(summary, ensure_ascii=False)},
        files={"result_file": result_path},
    )


def process_one(job_payload: dict) -> None:
    job = job_payload["job"]
    root = Path(env("CODEX_WORKER_ROOT", ".codex-form-worker")).resolve()
    job_dir = root / job["id"]
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "input").mkdir(exist_ok=True)

    print(f"[worker] 领取任务 {job['id']} ({job['form_type']})")
    local_assets = [(asset, download_asset(asset, job_dir)) for asset in job_payload["assets"]]
    output_path = job_dir / "output" / "result.xlsx"
    prompt = build_prompt(job_payload, local_assets, output_path)

    result_path, summary = run_codex(job_dir, prompt, local_assets)
    complete_job(job_payload, result_path, summary)
    print(f"[worker] 任务完成 {job['id']} -> {result_path}")


def poll_once() -> bool:
    payload = request_json("/api/forms/worker/jobs/next/", method="POST")
    if not payload.get("job"):
        return False

    try:
        process_one(payload)
    except Exception as exc:  # noqa: BLE001 - worker must report every failure
        message = f"{exc}\n{traceback.format_exc()}"
        print(f"[worker] 任务失败：{message}", file=sys.stderr)
        try:
            fail_job(payload, message, {"mode": "codex-skill-worker"})
        except Exception as report_exc:  # noqa: BLE001
            print(f"[worker] 回传失败原因失败：{report_exc}", file=sys.stderr)
    return True


def main() -> int:
    poll_seconds = int(env("CODEX_WORKER_POLL_SECONDS", "10"))
    run_once = env("CODEX_WORKER_RUN_ONCE") == "1"
    print("[worker] Creator Codex Form Worker started.")
    print(f"[worker] server={server_url()}")
    print(f"[worker] root={Path(env('CODEX_WORKER_ROOT', '.codex-form-worker')).resolve()}")

    while True:
        try:
            got_job = poll_once()
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] 轮询失败：{exc}", file=sys.stderr)
            got_job = False
        if run_once:
            return 0
        if not got_job:
            time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
