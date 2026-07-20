$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$tokenLine = Get-Content -LiteralPath '.\.env' |
    Where-Object { $_ -match '^\s*FORM_AUTOMATION_WORKER_TOKEN\s*=' } |
    Select-Object -First 1
if (-not $tokenLine) {
    throw 'FORM_AUTOMATION_WORKER_TOKEN was not found in .env.'
}

$workerToken = ($tokenLine -split '=', 2)[1].Trim().Trim([char]34).Trim([char]39)
if (-not $workerToken) {
    throw 'FORM_AUTOMATION_WORKER_TOKEN must not be empty.'
}

$codexExecutable = Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin\*\codex.exe" -ErrorAction Stop |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName

$env:CREATOR_SERVER_URL = 'http://127.0.0.1:8000'
$env:FORM_AUTOMATION_WORKER_TOKEN = $workerToken
$env:CODEX_BIN = $codexExecutable
$env:CODEX_WORKER_ROOT = 'C:\CreatorCodexLocalWorker'
$env:CODEX_WORKER_POLL_SECONDS = '5'
$env:CODEX_WORKER_TIMEOUT_SECONDS = '1800'
$env:CODEX_WORKER_EARLY_COMPLETE_SECONDS = '0'
$env:CODEX_WORKER_HEARTBEAT_SECONDS = '30'
$env:CODEX_WORKER_LOCAL_RETENTION_DAYS = '7'
$env:CODEX_WORKER_MIN_FREE_GB = '2'
$env:PYTHONUNBUFFERED = '1'

& '.\.venv\Scripts\python.exe' '-u' 'scripts\codex_form_worker.py'
