# ============================================================
# Gipfel · Windows 开发环境首次初始化（仅运行一次）
#
# 执行：
#   cd GipfelBusinessCompetitionManagerWeb
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap-dev.ps1
#
# 做什么：
#   1. 检查 Python/Node
#   2. 复制 backend\.env.example → backend\.env（如不存在）
#   3. backend\ 创建虚拟环境 + pip install -r requirements.txt
#   4. python manage.py migrate  # 首次会自动 seed admin/admin123
#   5. frontend\ npm install
# ============================================================
[CmdletBinding()]
param(
    [string]$BackendDir,
    [string]$FrontendDir,
    [switch]$SkipFrontend
)

# NOTE: do NOT use $PSScriptRoot inside param() defaults - PS 5.1 bug.
# NOTE: sanitize control chars / BOM from ALL paths before GetFullPath (经验 1383550).
function _CleanPath([string]$s) {
    if ([string]::IsNullOrEmpty($s)) { return $s }
    return [regex]::Replace($s, '[\u0000-\u001F\uFEFF]', '')
}
if ([string]::IsNullOrWhiteSpace($BackendDir)) {
    $BackendDir  = "$PSScriptRoot\..\backend"
}
if ([string]::IsNullOrWhiteSpace($FrontendDir)) {
    $FrontendDir = "$PSScriptRoot\..\frontend"
}

$ErrorActionPreference = "Stop"

function Write-Info  { Write-Host ("[INFO]  " + $args) -ForegroundColor Cyan }
function Write-OK    { Write-Host ("[OK]    " + $args) -ForegroundColor Green }
function Write-Warn  { Write-Host ("[WARN]  " + $args) -ForegroundColor Yellow }
function Write-Err   { Write-Host ("[ERROR] " + $args) -ForegroundColor Red }

# --------- 绝对路径归一化 ---------
$BackendDir  = _CleanPath $BackendDir
$FrontendDir = _CleanPath $FrontendDir
# Set current location so relative "..\" anchors resolve correctly for GetFullPath
Push-Location $PSScriptRoot
$BackendDir  = [System.IO.Path]::GetFullPath($BackendDir)
$FrontendDir = [System.IO.Path]::GetFullPath($FrontendDir)
Pop-Location

# --------- 1. 环境检查 ---------
Write-Info "检查运行环境..."
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Err "找不到 python，请先安装 Python 3.10+（建议 3.12）并加入 PATH，或重开终端刷新 PATH"
    exit 1
}
$pyVersion = (python -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')") 2>&1
Write-Info "  python: $pyVersion"
if ([version]$pyVersion -lt [version]"3.10") {
    Write-Err "Python 版本过低：$pyVersion（最低 3.10，推荐 3.12）"
    exit 1
}

if (-not $SkipFrontend) {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Err "找不到 node，请先安装 Node.js 18+（建议 20 LTS）并加入 PATH"
        exit 1
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Err "找不到 npm（应随 Node 一起安装）"
        exit 1
    }
    $nodeVer = (node -v).Trim()
    $npmVer  = (npm -v).Trim()
    Write-Info "  node: $nodeVer  npm: $npmVer"
}

# 必要文件检查
$reqTxt    = Join-Path $BackendDir "requirements.txt"
$envEx     = Join-Path $BackendDir ".env.example"
$pkgJson   = Join-Path $FrontendDir "package.json"
if (-not (Test-Path $reqTxt))  { Write-Err "缺少 $reqTxt"; exit 1 }
if (-not (Test-Path $envEx))   { Write-Err "缺少 $envEx";  exit 1 }
if (-not $SkipFrontend -and -not (Test-Path $pkgJson)) { Write-Err "缺少 $pkgJson"; exit 1 }

# --------- 2. .env ---------
$envFile = Join-Path $BackendDir ".env"
if (-not (Test-Path $envFile)) {
    Write-Info "首次部署：复制 .env.example -> .env"
    Copy-Item $envEx $envFile
    Write-Warn "  生产部署务必修改 JWT_SECRET 与 CORS_ORIGIN（当前为开发默认即可）"
} else {
    Write-Info ".env 已存在，跳过写入"
}

# --------- 3. Python 虚拟环境 + pip ---------
Push-Location $BackendDir
$venvDir = Join-Path $BackendDir ".venv"
$pyExe   = Join-Path $venvDir "Scripts\python.exe"
$pipExe  = Join-Path $venvDir "Scripts\pip.exe"

if (-not (Test-Path $pyExe)) {
    Write-Info "创建虚拟环境 .venv ..."
    python -m venv .venv
    if (-not (Test-Path $pyExe)) { Write-Err "虚拟环境创建失败"; exit 1 }
    Write-Info "升级 pip / setuptools / wheel ..."
    & $pipExe install --upgrade pip setuptools wheel | Out-Host
} else {
    Write-Info ".venv 已存在，跳过创建"
}

Write-Info "安装 Python 依赖（requirements.txt）..."
& $pipExe install -r requirements.txt | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Err "pip install 失败，退出码 $LASTEXITCODE"; exit 1 }
Write-OK "Python 依赖安装完成"

# --------- 4. migrate（seed admin/admin123 幂等） ---------
Write-Info "执行 Django check + migrate（首次 migrate 会自动建 admin / admin123）..."
& $pyExe manage.py check --fail-level ERROR | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Err "Django check 失败"; exit 1 }
& $pyExe manage.py migrate --noinput | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Err "migrate 失败"; exit 1 }
Write-OK "数据库迁移完成"

# 确认默认 admin 已创建
$n = & $pyExe -c "import os,sys;os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings');import django;django.setup();from apps.users.models import User;sys.stdout.write(str(User.objects.filter(username='admin').count()))"
Write-Info "  admin 用户数 = $n"
Pop-Location

# --------- 5. 前端依赖 ---------
if (-not $SkipFrontend) {
    Push-Location $FrontendDir
    $nmDir = Join-Path $FrontendDir "node_modules"
    if (Test-Path (Join-Path $nmDir ".package-lock.json")) {
        Write-Info "node_modules 已存在，执行 npm install 增量更新依赖..."
        npm install --no-audit --no-fund | Out-Host
    } else {
        Write-Info "首次安装前端依赖（npm install）..."
        npm install --no-audit --no-fund | Out-Host
    }
    if ($LASTEXITCODE -ne 0) { Write-Err "npm install 失败，退出码 $LASTEXITCODE"; exit 1 }
    Write-OK "前端依赖安装完成"
    Pop-Location
}

# --------- 收尾 ---------
Write-Host ""
Write-OK "初始化完成！下一步："
Write-Host "  1) 同时启动 Django + Vite："
Write-Host "     powershell -ExecutionPolicy Bypass -File scripts\start-dev.ps1"
Write-Host "  2) 浏览器打开 http://localhost:5173  登录 admin / admin123（首次强制改密）"
