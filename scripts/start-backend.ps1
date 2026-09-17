# 启动后端（供根目录 pnpm run api 使用）
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$backendDir = Join-Path $root 'backend'
Set-Location $backendDir

$py = $null
foreach ($p in @(
        (Join-Path $backendDir '.venv\Scripts\python.exe'),
        (Join-Path $root '.venv\Scripts\python.exe')
    )) {
    if (Test-Path $p) { $py = $p; break }
}
if (-not $py) {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { $py = $c.Source }
}
if (-not $py) {
    Write-Host '[error] Python not found. Create venv: cd backend; uv venv; uv pip install -r requirements.txt' -ForegroundColor Red
    exit 1
}

Write-Host "[api] $py run.py" -ForegroundColor Cyan
& $py run.py
