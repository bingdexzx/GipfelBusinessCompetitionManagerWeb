# ============================================================
#  Gipfel 高并发压力测试
#  用法: 双击 scripts\stress-test.bat，或
#        powershell -ExecutionPolicy Bypass -File scripts\stress-test.ps1
# ============================================================
[CmdletBinding()]
param(
    [string]$ServerUrl,
    [int]$Concurrent,
    [int]$Total,
    [string]$EndpointKey,
    [string]$Token,
    [switch]$NoSave
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_load-engine.ps1')

try {
    Write-GipfelBanner 'Gipfel 高并发压力测试工具'

    # ---------------- 参数收集 ----------------
    if ([string]::IsNullOrWhiteSpace($ServerUrl)) {
        $ServerUrl = Read-GipfelServerUrl
    } else {
        $ServerUrl = $ServerUrl.TrimEnd('/')
    }
    Write-Host ("服务器: {0}" -f $ServerUrl) -ForegroundColor Green
    Write-Host ''

    if (-not $Concurrent -or -not $Total) {
        Write-Host '请选择测试类型:' -ForegroundColor Yellow
        Write-Host '  1 - 快速测试      (10 并发,   100 请求)'
        Write-Host '  2 - 标准测试      (50 并发,   500 请求)'
        Write-Host '  3 - 压力测试      (100 并发, 1000 请求)'
        Write-Host '  4 - 高并发测试    (200 并发, 2000 请求)'
        Write-Host '  5 - 自定义'
        Write-Host ''
        switch ((Read-Host '请输入数字 (1-5)').Trim()) {
            '1' { $Concurrent = 10;  $Total = 100 }
            '2' { $Concurrent = 50;  $Total = 500 }
            '3' { $Concurrent = 100; $Total = 1000 }
            '4' { $Concurrent = 200; $Total = 2000 }
            '5' {
                $Concurrent = [int](Read-Host '并发数')
                $Total      = [int](Read-Host '总请求数')
            }
            default {
                Write-Host '无效选择，使用默认: 50 并发, 500 请求' -ForegroundColor Yellow
                $Concurrent = 50; $Total = 500
            }
        }
    }
    if ($Concurrent -lt 1) { $Concurrent = 1 }
    if ($Total -lt 1) { $Total = 1 }

    if ($EndpointKey) {
        $ep = $script:GipfelEndpoints | Where-Object { $_.Key -eq $EndpointKey } | Select-Object -First 1
        if (-not $ep) { $ep = $script:GipfelEndpoints[0] }
    } else {
        $ep = Read-GipfelEndpoint
    }

    $auth = Read-GipfelAuth -Endpoint $ep -ServerUrl $ServerUrl -Token $Token
    if ($auth.TokenSource) {
        Write-Host ("认证来源: {0}" -f $auth.TokenSource) -ForegroundColor DarkGray
    }

    # ---------------- Token 预检 ----------------
    # 先花 1 个请求确认鉴权能过，避免跑完上千请求才发现结果全是 401。
    if ($ep.Auth -and $auth.Token) {
        $chk = Test-GipfelAuth -ServerUrl $ServerUrl -Token $auth.Token
        if ($chk.Ok) {
            Write-Host 'Token 预检通过（/api/auth/me 返回 200）' -ForegroundColor Green
        } else {
            Write-Host ''
            Write-Host ("[警告] Token 预检失败：HTTP {0} {1}" -f $chk.StatusCode, $chk.Message) -ForegroundColor Red
            Write-Host '  继续跑的话结果会出现大量 401，数字没有参考价值。' -ForegroundColor Yellow
            if ((Read-Host '仍要继续? (y/N)') -notmatch '^[Yy]') {
                throw '已取消：请先取得有效 Token'
            }
        }
    }

    $url    = $ServerUrl + $ep.Path
    $method = $ep.Method
    $body   = ''
    if ($method -eq 'POST') {
        $body = New-GipfelLoginBody -User $auth.User -Pass $auth.Pass
    }

    # ---------------- 配置确认 ----------------
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ' 测试配置'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host (" 服务器:   {0}" -f $ServerUrl)
    Write-Host (" 端点:     {0} ({1})" -f $ep.Path, $ep.Name)
    Write-Host (" 方法:     {0}" -f $method)
    Write-Host (" 并发数:   {0}" -f $Concurrent)
    Write-Host (" 请求数:   {0}" -f $Total)
    if ($auth.Token) { Write-Host ' 认证:     Bearer Token 已设置' }
    if ($auth.User)  { Write-Host (" 登录用户: {0}" -f $auth.User) }
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''
    [void](Read-Host '按回车开始测试（Ctrl+C 取消）')

    # ---------------- 执行 ----------------
    Write-Host ''
    Write-Host ("正在测试 {0} ({1})，请稍候..." -f $ep.Name, $ep.Path) -ForegroundColor Cyan
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = Invoke-GipfelLoad -Url $url -Method $method -Body $body -Token $auth.Token `
                           -Concurrent $Concurrent -Total $Total -TimeoutSec 30
    $sw.Stop()

    # ---------------- 报告 ----------------
    $rate = if ($r.Total -gt 0) { $r.Success / $r.Total * 100 } else { 0 }
    $avgColor  = if ($r.Avg  -gt 500)  { 'Red' } else { 'Green' }
    $maxColor  = if ($r.Max  -gt 2000) { 'Red' } else { 'Green' }
    $p95Color  = if ($r.P95  -gt 1000) { 'Red' } else { 'Green' }

    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host '                    测试结果'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''
    Write-Host (" 目标端点:     {0}" -f $url)
    Write-Host (" 请求方法:     {0}" -f $method)
    Write-Host (" 总请求数:     {0}" -f $r.Total)
    Write-Host (" 成功请求:     {0}" -f $r.Success) -ForegroundColor Green
    Write-Host (" 失败请求:     {0}" -f $r.Fail) -ForegroundColor $(if ($r.Fail -gt 0) { 'Red' } else { 'Green' })
    Write-Host (" 成功率:       {0}%" -f [Math]::Round($rate, 2)) -ForegroundColor $(if ($rate -ge 95) { 'Green' } else { 'Red' })
    Write-Host (" 总耗时:       {0} 秒" -f [Math]::Round($r.Seconds, 2))
    Write-Host (" 每秒请求数:   {0} RPS" -f [Math]::Round($r.Rps, 2)) -ForegroundColor Cyan
    Write-Host ''
    Write-Host ' 响应时间:' -ForegroundColor Yellow
    Write-Host ("   最小值:     {0} ms" -f $r.Min)
    Write-Host ("   最大值:     {0} ms" -f $r.Max) -ForegroundColor $maxColor
    Write-Host ("   平均值:     {0} ms" -f [Math]::Round($r.Avg, 2)) -ForegroundColor $avgColor
    Write-Host ("   P50:        {0} ms" -f $r.P50)
    Write-Host ("   P95:        {0} ms" -f $r.P95) -ForegroundColor $p95Color
    Write-Host ("   P99:        {0} ms" -f $r.P99)
    Write-Host ''
    Write-Host ' 状态码分布:' -ForegroundColor Yellow
    foreach ($code in ($r.Codes.Keys | Sort-Object)) {
        $label = if ($code -eq 0) { '连接失败/超时' } else { [string]$code }
        $color = if ($code -ge 200 -and $code -lt 300) { 'Green' }
                 elseif ($code -eq 0) { 'Red' } else { 'Yellow' }
        Write-Host ("   {0,-16} {1} 次" -f $label, $r.Codes[$code]) -ForegroundColor $color
        # 非 2xx 时把后端返回的原因一并打出来（光看状态码分不清原因）
        if ($code -ne 0 -and ($code -lt 200 -or $code -ge 300)) {
            $why = Get-GipfelCodeReason -Result $r -Code $code
            if ($why) { Write-Host ("        └─ {0}" -f $why) -ForegroundColor DarkGray }
        }
    }

    # 401 专项诊断：按后端返回的 message 判定，而不是一律猜「顶号下线」
    $n401 = 0
    if ($r.Codes.ContainsKey(401)) { $n401 = $r.Codes[401] }
    if ($n401 -gt 0) {
        $why401 = Get-GipfelCodeReason -Result $r -Code 401
        Write-Host ''
        Write-Host ' [诊断] 出现 401，本次结果不可用于评估性能：' -ForegroundColor Yellow
        if ($why401 -match '需先修改初始密码') {
            Write-Host '   原因：账号带 must_change_password 标记 —— 除改密接口外全部接口一律 401。' -ForegroundColor DarkGray
            Write-Host '   token 本身有效，也与人是否在别处登录无关。' -ForegroundColor DarkGray
            Write-Host '   解决：先调 /api/auth/change-password 完成首次改密（新密码≥8位），' -ForegroundColor DarkGray
            Write-Host '         或对压测专用账号清掉该标记，或换一个无此标记的账号。' -ForegroundColor DarkGray
        } elseif ($why401 -match '已在其他设备登录') {
            Write-Host '   原因：token_version 不匹配（顶号下线）—— 测试期间该账号在别处登录过。' -ForegroundColor DarkGray
            Write-Host '   解决：用专用测试账号，测试期间不要在别处登录它。' -ForegroundColor DarkGray
        } elseif ($why401 -match '登录已过期') {
            Write-Host '   原因：JWT 解码失败/已过期/用户不存在。' -ForegroundColor DarkGray
            Write-Host '   常见成因：JWT_SECRET 被重新生成过（旧 token 全部作废），或 token 复制不完整。' -ForegroundColor DarkGray
        } elseif ($why401) {
            Write-Host ("   后端返回：{0}" -f $why401) -ForegroundColor DarkGray
        } else {
            Write-Host '   未取到响应体原因（可能是未带 Authorization 头，或响应体非 JSON）。' -ForegroundColor DarkGray
        }
    }
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan

    # ---------------- 保存报告 ----------------
    if (-not $NoSave) {
        $dir  = Get-GipfelResultDir -ScriptRoot $PSScriptRoot
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $base = Join-Path $dir ("stress-test-$stamp")

        $lines = @()
        $lines += ('=' * 60)
        $lines += 'Gipfel 高并发压力测试报告'
        $lines += ('=' * 60)
        $lines += ("测试时间: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
        $lines += ("服务器:   {0}" -f $ServerUrl)
        $lines += ("端点:     {0} ({1})" -f $ep.Path, $ep.Name)
        $lines += ("方法:     {0}" -f $method)
        $lines += ("并发数:   {0}" -f $Concurrent)
        $lines += ("请求数:   {0}" -f $r.Total)
        $lines += ''
        $lines += '测试结果:'
        $lines += ("  成功:     {0}" -f $r.Success)
        $lines += ("  失败:     {0}" -f $r.Fail)
        $lines += ("  成功率:   {0}%" -f [Math]::Round($rate, 2))
        $lines += ("  总耗时:   {0} 秒" -f [Math]::Round($r.Seconds, 2))
        $lines += ("  RPS:      {0}" -f [Math]::Round($r.Rps, 2))
        $lines += ''
        $lines += '响应时间:'
        $lines += ("  最小: {0} ms" -f $r.Min)
        $lines += ("  最大: {0} ms" -f $r.Max)
        $lines += ("  平均: {0} ms" -f [Math]::Round($r.Avg, 2))
        $lines += ("  P50:  {0} ms" -f $r.P50)
        $lines += ("  P95:  {0} ms" -f $r.P95)
        $lines += ("  P99:  {0} ms" -f $r.P99)
        $lines += ''
        $lines += '状态码分布:'
        foreach ($code in ($r.Codes.Keys | Sort-Object)) {
            $label = if ($code -eq 0) { '连接失败/超时' } else { [string]$code }
            $line = "  {0}: {1} 次" -f $label, $r.Codes[$code]
            if ($code -ne 0 -and ($code -lt 200 -or $code -ge 300)) {
                $why = Get-GipfelCodeReason -Result $r -Code $code
                if ($why) { $line += ("   原因: " + $why) }
            }
            $lines += $line
        }
        $lines += ('=' * 60)

        $lines | Out-File -FilePath "$base.txt" -Encoding UTF8

        # 每条请求的耗时明细（升序），便于用 Excel 画分布
        $csv = for ($i = 0; $i -lt $r.Latencies.Length; $i++) {
            [pscustomobject]@{ 序号 = $i + 1; 响应时间ms = $r.Latencies[$i] }
        }
        $csv | Export-Csv -Path "$base.csv" -NoTypeInformation -Encoding UTF8

        Write-Host ''
        Write-Host ("报告已保存: {0}.txt" -f $base) -ForegroundColor Green
        Write-Host ("明细已保存: {0}.csv" -f $base) -ForegroundColor Green
    }
}
catch {
    Write-Host ''
    Write-Host ('[错误] ' + $_.Exception.Message) -ForegroundColor Red
}
finally {
    Write-Host ''
    [void](Read-Host '按回车退出')
}
