# Codex Worker 部署说明：报销表格自动化

这个方案把报销/采购自动化拆成两部分：

1. 阿里云 Django 网站：负责上传材料、创建任务、保存结果、提供下载。
2. Windows Codex Worker：负责领取任务、调用 `$expense-procurement-forms` skill、用 Excel COM 嵌入发票原文件、生成 `.xlsx` 并回传。

费用报销表需要 Windows + Microsoft Excel COM 才能把 PDF/图片发票作为原文件对象嵌入 Excel，因此 Worker 不建议跑在 Ubuntu 阿里云 ECS 上。

## 阿里云服务器配置

把项目更新到包含 Worker API 的版本后，在阿里云项目目录执行：

```bash
cd /var/www/creator
git pull --ff-only origin main
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
```

生成一个长随机 Worker Token：

```bash
python - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
```

把下面两行加入你的 Django 服务环境变量。示例使用 `/etc/creator.env`，如果你的项目不是这样加载环境变量，请放到你实际的 systemd 环境文件里：

```bash
sudo sh -c 'cat >> /etc/creator.env' <<'EOF'
FORM_AUTOMATION_BACKEND=codex_worker
FORM_AUTOMATION_WORKER_TOKEN=把上一步生成的长随机token粘贴到这里
EOF
```

重启 Django 服务，并重新构建前端：

```bash
sudo systemctl restart creator
cd /var/www/creator/frontend
npm ci
npm run build
sudo nginx -t
sudo systemctl reload nginx
```

如果你的 systemd 服务名不是 `creator`，把 `sudo systemctl restart creator` 替换成你实际的服务名，例如 `gunicorn`、`creator-backend` 等。

检查网站是否进入 Worker 模式：

```bash
curl http://127.0.0.1:8000/api/forms/health/
```

返回里的 `capabilities.backend` 应该是：

```json
"codex_worker"
```

## Windows Codex Worker 配置

Windows Worker 机器需要：

- 已登录并可运行 Codex CLI；
- 已安装 Microsoft Excel；
- 已有 `C:\Users\Administrator\.codex\skills\expense-procurement-forms` skill；
- 已拉取同一份网站项目代码。

在 Windows PowerShell 中：

```powershell
cd C:\Users\Administrator\Documents\work06-Creator
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

设置环境变量并启动 Worker：

```powershell
$env:CREATOR_SERVER_URL = "http://120.79.5.18"
$env:FORM_AUTOMATION_WORKER_TOKEN = "和阿里云 FORM_AUTOMATION_WORKER_TOKEN 完全相同的 token"
$env:CODEX_BIN = "codex"
$env:CODEX_WORKER_ROOT = "C:\CreatorCodexWorker"
$env:CODEX_WORKER_POLL_SECONDS = "10"
$env:CODEX_WORKER_TIMEOUT_SECONDS = "1800"

.\.venv\Scripts\python.exe scripts\codex_form_worker.py
```

如果 PowerShell 提示 `codex` 无法运行，说明当前 Windows 环境没有可用于命令行的 Codex CLI。需要先让 `codex exec` 能正常运行，再启动 Worker。

单次测试模式：

```powershell
$env:CODEX_WORKER_RUN_ONCE = "1"
.\.venv\Scripts\python.exe scripts\codex_form_worker.py
```

## 工作流

1. 用户在网站上传材料并提交。
2. Django 创建 `pending` 任务。
3. Windows Worker 调用 `/api/forms/worker/jobs/next/` 领取任务。
4. Worker 下载所有材料到本地任务目录。
5. Worker 调用：

   ```powershell
   codex exec --cd <job-dir> --sandbox danger-full-access --ask-for-approval never --skip-git-repo-check --output-last-message <file> "请读取并执行 task.md 中的后台任务。"
   ```

6. Codex 使用 `$expense-procurement-forms` 生成 Excel。
7. Worker 上传生成的 `.xlsx`。
8. 网站状态变成 `success`，用户可以下载。

