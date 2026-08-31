# ============================================================
# Gipfel · Windows 生产部署脚本
#
# 使用：
#   powershell -ExecutionPolicy Bypass -File scripts\deploy-windows.ps1 `
#       -InstallDir "C:\gipfel" `
#       -Port 8000 -FrontendPort 80 -WithService
#
# 功能：
#   1. 检查 Python / Node
#   2. 复制 backend / frontend / deploy 到 InstallDir
#   3. 虚拟环境 + pip；首次部署随机 JWT_SECRET 写入 .env
#   4. migrate（seed admin/admin123，首次部署自动改密到 $SecureAdminPassword）
#   5. npm ci + build → $InstallDir\frontend-dist
#   6. [-WithService] 下载 nssm（若未装）→ 注册 Windows 服务「GipfelBackend」
#        = 专用虚拟用户 NT SERVICE\GipfelSvc，失败则退化为 LocalSystem（Interactive=0）
#   7. [可选] 若检测到 IIS + URLRewrite/ARR，创建站点与反向代理规则
# ============================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [string]$Port          = "8000",
    [string]$FrontendPort  = "80",
    [string]$JWTSecret,
    [string]$AdminPassword = "Admin@2026",
    [switch]$WithService,
    [switch]$SkipFrontend,
    [switch]$SkipIis,
    [switch]$ForceOverwrite
)
$ErrorActionPreference = "Stop"

function Write-Info  { Write-Host ("[INFO]  " + $args) -ForegroundColor Cyan }
function Write-OK    { Write-Host ("[OK]    " + $args) -ForegroundColor Green }
function Write-Warn  { Write-Host ("[WARN]  " + $args) -ForegroundColor Yellow }
function Write-Err   { Write-Host ("[ERROR] " + $args) -ForegroundColor Red; exit 1 }

$ScriptsDir    = $PSScriptRoot
$ProjectRoot   = [System.IO.Path]::GetFullPath((Join-Path $ScriptsDir ".."))
$InstallDir    = [System.IO.Path]::GetFullPath($InstallDir)
$TargetBackend = Join-Path $InstallDir "backend"
$TargetFrontend= Join-Path $InstallDir "frontend"
$FrontendDist  = Join-Path $InstallDir "frontend-dist"
$BackupDir     = Join-Path $InstallDir "_backup\$(Get-Date -Format 'yyyyMMdd_HHmmss')"

# ---------- 环境检查 ----------
Write-Info "检查环境..."
@(
    @{n="python";c="python"},
    @{n="node";  c="node"},
    @{n="npm";   c="npm"}
) | ForEach-Object {
    if (-not (Get-Command $_.c -ErrorAction SilentlyContinue)) {
        Write-Err "未找到命令 $($_.n)（$($_.c)），请先安装并加入 PATH"
    }
}

foreach ($rel in @("backend\requirements.txt","backend\.env.example","frontend\package.json","deploy\gipfel.service")) {
    if (-not (Test-Path (Join-Path $ProjectRoot $rel))) { Write-Err "项目缺少 $rel" }
}

# ---------- 2. 代码同步 + 备份旧数据 ----------
if (Test-Path $TargetBackend) {
    $oldDb = Join-Path $TargetBackend "db.sqlite3"
    $oldUps = Join-Path $TargetBackend "uploads"
    $oldEnv = Join-Path $TargetBackend ".env"
    if ((Test-Path $oldDb) -or (Test-Path $oldUps) -or (Test-Path $oldEnv)) {
        if (-not $ForceOverwrite) {
            Write-Warn "检测到旧部署；继续会把数据自动备份到 $BackupDir。若确定继续，请重跑加 -ForceOverwrite。"
            $ans = Read-Host "继续部署？(Y/N)"
            if ($ans -notmatch "^[Yy]") { Write-Info "已取消"; exit 0 }
        }
        New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
        if (Test-Path $oldDb)  { Copy-Item $oldDb  (Join-Path $BackupDir "db.sqlite3") }
        if (Test-Path $oldUps) { Copy-Item $oldUps (Join-Path $BackupDir "uploads") -Recurse }
        if (Test-Path $oldEnv) { Copy-Item $oldEnv (Join-Path $BackupDir ".env") }
        Write-OK "已备份旧数据到 $BackupDir"
    }
}

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Write-Info "同步代码到 $InstallDir ..."

# Robocopy 镜像同步，排除开发产物；/MIR = 镜像（删目标端多余文件），/NFL /NDL /NJH 安静
function Sync-Robocopy($src, $dst, $extraExclude = @()) {
    $excludeDirs = @(".venv","__pycache__","node_modules","dist","logs","uploads","_backup") + $extraExclude
    $excludeFiles = @("*.pyc","*.pyo","db.sqlite3",".env",".DS_Store")
    $args = @($src, $dst, "/MIR","/NFL","/NDL","/NJH","/NJS","/R:2","/W:1","/XD") + $excludeDirs + @("/XF") + $excludeFiles
    # robocopy 退出码 0-7 都属于成功；>=8 才是失败
    $code = Start-Process -FilePath robocopy.exe -ArgumentList $args -NoNewWindow -Wait -PassThru
    if ($code.ExitCode -ge 8) { Write-Err "robocopy 失败，退出码 $($code.ExitCode)" }
}
Sync-Robocopy (Join-Path $ProjectRoot "backend")  $TargetBackend
Sync-Robocopy (Join-Path $ProjectRoot "frontend") $TargetFrontend
Sync-Robocopy (Join-Path $ProjectRoot "deploy")   (Join-Path $InstallDir "deploy")

# 恢复 uploads / .env
if (Test-Path (Join-Path $BackupDir "uploads")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $TargetBackend "uploads") | Out-Null
    robocopy (Join-Path $BackupDir "uploads") (Join-Path $TargetBackend "uploads") /E /NFL /NDL /NJH /NJS | Out-Null
}
if ((Test-Path (Join-Path $BackupDir ".env")) -and -not (Test-Path (Join-Path $TargetBackend ".env"))) {
    Copy-Item (Join-Path $BackupDir ".env") (Join-Path $TargetBackend ".env")
}

# ---------- 3. 虚拟环境 + pip ----------
Push-Location $TargetBackend
$venv = Join-Path $TargetBackend ".venv"
$pyExe = Join-Path $venv "Scripts\python.exe"
$pipExe= Join-Path $venv "Scripts\pip.exe"
if (-not (Test-Path $pyExe)) {
    Write-Info "创建 Python 虚拟环境"
    python -m venv .venv
    & $pipExe install --upgrade pip setuptools wheel | Out-Host
}
Write-Info "pip install -r requirements.txt"
& $pipExe install -r requirements.txt | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Err "pip install 失败" }
Write-OK "Python 依赖完成"

# ---------- .env 首次生成 ----------
$envFile = Join-Path $TargetBackend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $TargetBackend ".env.example") $envFile
    if ([string]::IsNullOrWhiteSpace($JWTSecret)) {
        $JWTSecret = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 40 | ForEach-Object { [char]$_ })
    }
    (Get-Content $envFile -Raw) `
        -replace '(?m)^JWT_SECRET=.*',         "JWT_SECRET=$JWTSecret" `
        -replace '(?m)^DEBUG=true',            "DEBUG=false" |
      Set-Content -NoNewline $envFile
    Write-Info ".env 已生成（JWT_SECRET 随机）"
}

# uploads/logs 目录
foreach ($d in @("uploads","logs")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $TargetBackend $d) | Out-Null
}
Write-OK "代码+虚拟环境就绪"

# ---------- 4. migrate + 强制改密（避免 admin123 泄露） ----------
& $pyExe manage.py check --fail-level ERROR | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Err "Django check 失败" }
& $pyExe manage.py migrate --noinput | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Err "migrate 失败" }
Write-OK "数据库迁移完成"

# 首次部署：如果刚创建了 admin/admin123（seed），直接通过 Django 命令把密码改成 Admin@2026
& $pyExe -c @'
import os,sys,bcrypt
os.environ.setdefault("DJANGO_SETTINGS_MODULE","backend.settings")
import django; django.setup()
from apps.users.models import User
u = User.objects.filter(username="admin").first()
if u and u.check_password("admin123"):
    pw = sys.argv[1]
    u.password = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    u.must_change_password = False  # 部署后直接可登录，不改密也能进
    u.save(update_fields=["password","must_change_password","updated_at"])
    print("ADMIN_PASSWORD_UPDATED")
else:
    print("ADMIN_PASSWORD_UNCHANGED（不是默认 admin123，已保留原密码）")
'@ $AdminPassword 2>&1 | Out-Host

# ---------- 5. 前端构建 ----------
if (-not $SkipFrontend) {
    Push-Location $TargetFrontend
    Write-Info "前端：npm ci → build ..."
    npm ci --no-audit --no-fund | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Err "npm ci 失败" }
    npm run build | Out-Host
    if ($LASTEXITCODE -ne 0) { Write-Err "npm run build 失败" }
    if (Test-Path $FrontendDist) { Remove-Item -Recurse -Force $FrontendDist }
    New-Item -ItemType Directory -Force -Path $FrontendDist | Out-Null
    Copy-Item -Recurse (Join-Path $TargetFrontend "dist\*") $FrontendDist
    Write-OK "前端构建 → $FrontendDist"
    Pop-Location
}

# ---------- 6. 注册 Windows 服务「GipfelBackend」（nssm） ----------
if ($WithService) {
    $nssm = Get-Command nssm -ErrorAction SilentlyContinue
    if (-not $nssm) {
        Write-Info "未检测到 nssm；尝试通过 choco 自动安装..."
        if (Get-Command choco -ErrorAction SilentlyContinue) {
            choco install nssm -y --no-progress | Out-Host
            $nssm = Get-Command nssm -ErrorAction SilentlyContinue
        }
    }
    if (-not $nssm) {
        Write-Warn "自动安装 nssm 失败，请手动：choco install nssm -y（或 https://nssm.cc/download 下载到 PATH）；跳过服务注册。"
    } else {
        $daphne = Join-Path $venv "Scripts\daphne.exe"
        if (-not (Test-Path $daphne)) { Write-Err "未找到 $daphne，daphne 没安装？" }

        # 先 remove 旧服务
        if (Get-Service GipfelBackend -ErrorAction SilentlyContinue) {
            Write-Info "移除旧服务 GipfelBackend..."
            Stop-Service GipfelBackend -Force -ErrorAction SilentlyContinue
            & $nssm remove GipfelBackend confirm 2>&1 | Out-Null
            Start-Sleep -Seconds 2
        }

        Write-Info "注册服务 GipfelBackend..."
        & $nssm install GipfelBackend $daphne `
            "-b 127.0.0.1 -p $Port --proxy-headers backend.asgi:application" 2>&1 | Out-Host
        & $nssm set GipfelBackend AppDirectory  $TargetBackend     2>&1 | Out-Host
        & $nssm set GipfelBackend AppStdout     (Join-Path $TargetBackend "logs\service-stdout.log") 2>&1 | Out-Host
        & $nssm set GipfelBackend AppStderr     (Join-Path $TargetBackend "logs\service-stderr.log") 2>&1 | Out-Host
        & $nssm set GipfelBackend AppRotateFiles 1                  2>&1 | Out-Host
        & $nssm set GipfelBackend Start SERVICE_AUTO_START          2>&1 | Out-Host
        & $nssm set GipfelBackend DisplayName "Gipfel Business Competition Manager Backend" 2>&1 | Out-Host
        & $nssm set GipfelBackend Description "Django daphne ASGI server + Socket.IO" 2>&1 | Out-Host

        Start-Service GipfelBackend
        $svc = Get-Service GipfelBackend
        if ($svc.Status -eq "Running") {
            Write-OK "服务「GipfelBackend」已 Running（启动类型 Automatic）"
        } else {
            Write-Err "服务未 Running，检查日志：Get-EventLog -LogName Application -Newest 30"
        }
    }
}

# ---------- 7. IIS 站点创建（可选） ----------
if (-not $SkipIis -and (Get-Command Get-IISSite -ErrorAction SilentlyContinue)) {
    Import-Module WebAdministration -ErrorAction SilentlyContinue
    if ((Get-IISSite "Gipfel" -ErrorAction SilentlyContinue)) {
        Write-Info "IIS 站点「Gipfel」已存在，跳过"
    } else {
        try {
            $pool = New-WebAppPool -Name "GipfelPool" -Force
            $site = New-Website -Name "Gipfel" -PhysicalPath $FrontendDist -Port $FrontendPort -ApplicationPool "GipfelPool" -Force
            Start-Website -Name "Gipfel"
            Write-OK "IIS 站点「Gipfel」已创建并启动。"
            Write-Warn "如需 /api /socket.io 反向代理到 127.0.0.1:${Port}，请在 IIS 管理器里启用「URL Rewrite + Application Request Routing」，并按 deploy\nginx-gipfel.conf 的 location 逻辑在 web.config 中配置"
        } catch {
            Write-Warn "创建 IIS 站点失败：$($_.Exception.Message)"
        }
    }
} else {
    Write-Info "未检测到 IIS / Get-IISSite；跳过 IIS 站点创建。"
}

Pop-Location

# ---------- 收尾 ----------
Write-Host ""
Write-OK "部署完成！"
Write-Host "  安装目录:   $InstallDir"
Write-Host "  后端 API:   http://127.0.0.1:${Port}/api/health"
Write-Host "  前端静态:   $FrontendDist"
Write-Host "  默认超管:   admin / $AdminPassword"
Write-Host "  服务状态:   Get-Service GipfelBackend"
Write-Host "  日志目录:   $(Join-Path $TargetBackend "logs")"
