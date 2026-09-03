$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$logDirectory = Join-Path $projectRoot '.runtime-logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

& '.\.venv\Scripts\python.exe' 'manage.py' 'runserver' '127.0.0.1:8000' '--noreload' *>> (Join-Path $logDirectory 'django-local.log')
exit $LASTEXITCODE
