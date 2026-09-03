$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendRoot = Join-Path $projectRoot 'frontend'
$bundledNode = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$viteEntry = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'

if (-not (Test-Path -LiteralPath $bundledNode)) {
    throw 'Bundled Node.js runtime was not found.'
}
if (-not (Test-Path -LiteralPath $viteEntry)) {
    throw 'Vite was not found. Restore frontend dependencies first.'
}

$logDirectory = Join-Path $projectRoot '.runtime-logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
Set-Location $frontendRoot

& $bundledNode $viteEntry '--host' '127.0.0.1' *>> (Join-Path $logDirectory 'frontend-local.log')
exit $LASTEXITCODE
