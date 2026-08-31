# ============================================================
# Gipfel · Windows 开发启动（Django 8000 + Vite 5173 并行）
#
# 依赖：先执行过 scripts\bootstrap-dev.ps1
#
# 执行：
#   cd GipfelBusinessCompetitionManagerWeb
#   powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1
#
# 特性：
#   - 启动两个后台进程（Django + Vite），它们的 stdout/stderr 直接流式输出到
#     当前控制台（不写日志文件）
#   - Ctrl+C 时自动 Stop-Process 两个子进程（try/finally 保证清理）
#   - 启动前做存活探活，控制台打印两个 URL
#   - 任何子进程异常退出都会打印错误并退出（界面停住，不再写日志）
# ============================================================
[CmdletBinding()]
param(
    [string]$BackendDir,
    [string]$FrontendDir,
    [string]$BackendBind  = "127.0.0.1:8000",
    [string]$VitePort     = "5173",
    [switch]$OpenBrowser
)

# NOTE: do NOT use $PSScriptRoot inside param() defaults - PS 5.1 bug.
# Strip BOM + control chars from ALL paths before IO.Path (经验 1383550).
function _CleanPath([string]$s) {
    if ([string]::IsNullOrEmpty($s)) { return $s }
    return [regex]::Replace($s, '[\u0000-\u001F\uFEFF]', '')
}
if ([string]::IsNullOrWhiteSpace($BackendDir))  { $BackendDir  = "$PSScriptRoot\..\backend" }
if ([string]::IsNullOrWhiteSpace($FrontendDir)) { $FrontendDir = "$PSScriptRoot\..\frontend" }

$ErrorActionPreference = "Stop"

function Write-Info  { Write-Host ("[INFO]  " + $args) -ForegroundColor Cyan }
function Write-OK    { Write-Host ("[OK]    " + $args) -ForegroundColor Green }
function Write-Warn  { Write-Host ("[WARN]  " + $args) -ForegroundColor Yellow }
function Write-Err   { Write-Host ("[ERROR] " + $args) -ForegroundColor Red }

Push-Location $PSScriptRoot
$BackendDir  = [System.IO.Path]::GetFullPath((_CleanPath $BackendDir))
$FrontendDir = [System.IO.Path]::GetFullPath((_CleanPath $FrontendDir))
Pop-Location

$BackendHost, $BackendPort = $BackendBind.Split(":", 2)
$backendProc = $null
$viteProc    = $null

# 前置检查：venv 与前端依赖是否就绪
$pyExe  = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (-not (Test-Path $pyExe)) {
    Write-Err "找不到 $pyExe。请先运行：scripts\bootstrap-dev.ps1"
    exit 1
}
if (-not (Test-Path (Join-Path $FrontendDir "node_modules\.bin\vite.cmd"))) {
    Write-Err "前端依赖未安装，请先运行：scripts\bootstrap-dev.ps1"
    exit 1
}

try {
    # --- 1) 启动 Django（runserver，--noreload 便于 Ctrl+C 快速退出）---
    Write-Info "启动 Django -> $BackendBind"
    $backendProc = Start-Process -FilePath $pyExe `
        -ArgumentList @("manage.py", "runserver", $BackendBind, "--noreload") `
        -WorkingDirectory $BackendDir `
        -UseNewEnvironment:$false `
        -PassThru -NoNewWindow
    Start-Sleep -Milliseconds 500
    if ($backendProc.HasExited) {
        Write-Err "Django 立即退出（退出码 $($backendProc.ExitCode)），请查看上方报错"
        exit 1
    }

    # 探活：最多 12s
    $probe = "http://${BackendHost}:${BackendPort}/api/health"
    Write-Info "探活 Django $probe ..."
    for ($i = 0; $i -lt 24; $i++) {
        try {
            $r = Invoke-RestMethod -Uri $probe -Method Get -TimeoutSec 2 -ErrorAction Stop
            if ($r.ok) { Write-OK "Django 就绪"; break }
        } catch {}
        Start-Sleep -Milliseconds 500
    }

    # --- 2) 启动 Vite ---
    Write-Info "启动 Vite -> 127.0.0.1:${VitePort}"
    $env:VITE_PORT = $VitePort
    $viteProc = Start-Process npm.cmd `
        -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", $VitePort) `
        -WorkingDirectory $FrontendDir `
        -PassThru -NoNewWindow
    Start-Sleep -Milliseconds 500
    if ($viteProc.HasExited) {
        Write-Err "Vite 立即退出（退出码 $($viteProc.ExitCode)），请查看上方报错"
        exit 1
    }

    # Vite 探活：最多 15s（第一次启动可能冷编译）
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $null = Invoke-WebRequest -Uri "http://127.0.0.1:${VitePort}/" -Method Head -TimeoutSec 2 -ErrorAction Stop
            Write-OK "Vite 就绪"
            break
        } catch {}
        Start-Sleep -Milliseconds 500
    }

    # --- 打开浏览器 ---
    if ($OpenBrowser) {
        Start-Process "http://127.0.0.1:${VitePort}/"
    }

    Write-Host ""
    Write-OK "服务已全部启动"
    Write-Host "  前端(Vite) : http://127.0.0.1:${VitePort}"
    Write-Host "  后端(Django): http://${BackendBind}"
    Write-Host "  Django / Vite 的输出会实时显示在本窗口（不写日志文件）"
    Write-Host ""
    Write-Warn "Ctrl + C 会停止两个子进程并退出"

    # --- 保活：直到收到 Ctrl+C 或两个子进程都退出 ---
    while ($true) {
        Start-Sleep -Milliseconds 500
        if ($backendProc.HasExited) { Write-Warn "Django 已退出，退出码 $($backendProc.ExitCode)" }
        if ($viteProc.HasExited)    { Write-Warn "Vite 已退出，退出码 $($viteProc.ExitCode)" }
        if ($backendProc.HasExited -and $viteProc.HasExited) { break }
    }
} finally {
    Write-Host ""
    Write-Warn "正在停止子进程..."
    foreach ($p in @($backendProc, $viteProc)) {
        if ($null -ne $p -and -not $p.HasExited) {
            try {
                Stop-Process -Id $p.Id -Force -ErrorAction Stop
                Write-Info "已停止 PID $($p.Id)"
            } catch {
                Write-Warn "停止 PID $($p.Id) 失败：$_"
            }
        }
    }
    Write-OK "已退出"
}
