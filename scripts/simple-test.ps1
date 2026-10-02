# ============================================================
#  Gipfel 简单连通性测试
#  用法: 双击 scripts\simple-test.bat（或 test-simple.bat）
#        powershell -ExecutionPolicy Bypass -File scripts\simple-test.ps1
# ============================================================
[CmdletBinding()]
param(
    [string]$ServerUrl,
    [int]$Count = 10,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'

try {
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host '  Gipfel 简单连通性测试'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''

    if ([string]::IsNullOrWhiteSpace($ServerUrl)) {
        $ServerUrl = (Read-Host '请输入服务器地址 (例如: http://your-domain.com)').Trim()
    }
    if ([string]::IsNullOrWhiteSpace($ServerUrl)) { throw '服务器地址不能为空！' }
    if (-not $ServerUrl.StartsWith('http://') -and -not $ServerUrl.StartsWith('https://')) {
        $ServerUrl = 'http://' + $ServerUrl
    }
    $ServerUrl = $ServerUrl.TrimEnd('/')

    # ---------------- 1. 端点可达性 ----------------
    Write-Host ("目标: {0}" -f $ServerUrl)
    Write-Host ''
    Write-Host '端点可达性:' -ForegroundColor Yellow
    Write-Host ''

    $probes = @(
        @{ Path = '/api/health';  Name = '健康检查' },
        @{ Path = '/api/version'; Name = '版本信息' },
        @{ Path = '/';            Name = '首页' }
    )
    $allOk = $true
    foreach ($p in $probes) {
        $u = $ServerUrl + $p.Path
        Write-Host ("  {0,-10} ({1,-13}) ... " -f $p.Name, $p.Path) -NoNewline
        try {
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $resp = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
            $sw.Stop()
            Write-Host ("OK {0} ({1} ms)" -f [int]$resp.StatusCode, $sw.ElapsedMilliseconds) -ForegroundColor Green
        } catch {
            $allOk = $false
            $code = $null
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
            if ($code) {
                Write-Host ("HTTP {0}" -f $code) -ForegroundColor Yellow
            } else {
                Write-Host ("失败: {0}" -f $_.Exception.Message) -ForegroundColor Red
            }
        }
    }

    # ---------------- 2. 顺序请求延迟采样 ----------------
    Write-Host ''
    Write-Host ("顺序请求采样 ({0} 次 -> /api/health):" -f $Count) -ForegroundColor Yellow
    Write-Host ''

    $target = $ServerUrl + '/api/health'
    $times = New-Object System.Collections.Generic.List[int]
    for ($i = 1; $i -le $Count; $i++) {
        Write-Host ("  请求 {0,2}: " -f $i) -NoNewline
        try {
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $resp = Invoke-WebRequest -Uri $target -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
            $sw.Stop()
            $ms = [int]$sw.ElapsedMilliseconds
            $times.Add($ms)
            Write-Host ("状态 {0}   {1} ms" -f [int]$resp.StatusCode, $ms)
        } catch {
            $code = '---'
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
            Write-Host ("状态 {0}   连接失败" -f $code) -ForegroundColor Red
        }
    }

    if ($times.Count -gt 0) {
        $sorted = $times | Sort-Object
        $avg = ($times | Measure-Object -Average).Average
        Write-Host ''
        Write-Host '采样统计:' -ForegroundColor Yellow
        Write-Host ("  成功: {0} / {1}" -f $times.Count, $Count)
        Write-Host ("  最小: {0} ms" -f $sorted[0])
        Write-Host ("  最大: {0} ms" -f $sorted[-1])
        Write-Host ("  平均: {0} ms" -f [Math]::Round($avg, 2))
    }

    Write-Host ''
    if ($allOk) {
        Write-Host '连通性测试完成：所有端点可达。' -ForegroundColor Green
    } else {
        Write-Host '连通性测试完成：部分端点不可达，请看上方逐项结果。' -ForegroundColor Yellow
    }
    Write-Host ''
}
catch {
    Write-Host ''
    Write-Host ('[错误] ' + $_.Exception.Message) -ForegroundColor Red
}
finally {
    if (-not $NoPause) {
        Write-Host ''
        [void](Read-Host '按回车退出')
    }
}
