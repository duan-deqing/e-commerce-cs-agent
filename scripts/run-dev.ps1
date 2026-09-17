# 一键启动：后端 FastAPI + 前端 Vite（React）
# 用法（仓库根目录）：
#   powershell -ExecutionPolicy Bypass -File .\run-dev.ps1
#   或： .\run-dev.ps1
# Ctrl+C 结束两个进程

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$backendDir = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'

# 优先使用 backend/.venv，其次仓库根 .venv，否则 PATH 中的 python
$backendPython = $null
$candidates = @(
    (Join-Path $backendDir '.venv\Scripts\python.exe'),
    (Join-Path $root '.venv\Scripts\python.exe')
)
foreach ($p in $candidates) {
    if (Test-Path $p) { $backendPython = $p; break }
}
if (-not $backendPython) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $backendPython = $cmd.Source }
}
if (-not $backendPython) {
    Write-Host '[error] 未找到 Python，请先在 backend 创建 venv： uv venv && uv pip install -r requirements.txt' -ForegroundColor Red
    exit 1
}

$pnpm = $null
$pnpmCmd = Get-Command pnpm -ErrorAction SilentlyContinue
if ($pnpmCmd) { $pnpm = $pnpmCmd.Source }
if (-not $pnpm) {
    Write-Host '[error] 未找到 pnpm，请先安装： npm i -g pnpm' -ForegroundColor Red
    exit 1
}
# Windows 上 pnpm 常为 pnpm.cmd
if ($pnpm -notmatch '\.cmd$' -and (Test-Path ($pnpm + '.cmd'))) {
    $pnpm = $pnpm + '.cmd'
}

Write-Host '========================================' -ForegroundColor DarkGray
Write-Host ' Orbit Desk — backend :8000 + frontend :5173' -ForegroundColor Cyan
Write-Host " python : $backendPython" -ForegroundColor DarkGray
Write-Host " pnpm   : $pnpm" -ForegroundColor DarkGray
Write-Host '========================================' -ForegroundColor DarkGray

$backend = Start-Process -FilePath $backendPython `
    -ArgumentList 'run.py' `
    -WorkingDirectory $backendDir `
    -PassThru `
    -NoNewWindow

$frontend = Start-Process -FilePath $pnpm `
    -ArgumentList 'dev' `
    -WorkingDirectory $frontendDir `
    -PassThru `
    -NoNewWindow

Write-Host ''
Write-Host '[backend ] http://127.0.0.1:8000  (docs: /docs)' -ForegroundColor Green
Write-Host '[frontend] http://localhost:5173' -ForegroundColor Green
Write-Host '[stop   ] Ctrl+C 会尝试结束两个进程' -ForegroundColor Yellow
Write-Host ''

try {
    Wait-Process -Id $backend.Id, $frontend.Id -ErrorAction SilentlyContinue
} finally {
    foreach ($proc in @($backend, $frontend)) {
        if ($proc -and -not $proc.HasExited) {
            Write-Host "stopping pid $($proc.Id)..." -ForegroundColor DarkGray
            try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}
