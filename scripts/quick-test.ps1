# ============================================================
#  Gipfel 快速高并发检查（带性能评分与优化建议）
#  用法: 双击 scripts\quick-test.bat，或
#        powershell -ExecutionPolicy Bypass -File scripts\quick-test.ps1
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
    Write-GipfelBanner 'Gipfel 快速高并发检查工具'

    if ([string]::IsNullOrWhiteSpace($ServerUrl)) {
        $ServerUrl = Read-GipfelServerUrl
    } else {
        $ServerUrl = $ServerUrl.TrimEnd('/')
    }

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

    # Token 预检：先花 1 个请求确认鉴权能过，避免整轮结果被 401 污染
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

    if (-not $Concurrent -or -not $Total) {
        Write-Host ''
        Write-Host '请选择测试级别:' -ForegroundColor Yellow
        Write-Host '  1. 快速检查       (20 并发,   200 请求)'
        Write-Host '  2. 中等检查       (50 并发,   500 请求)'
        Write-Host '  3. 高并发检查     (100 并发, 1000 请求)'
        Write-Host '  4. 超高并发检查   (200 并发, 2000 请求)'
        Write-Host ''
        switch ((Read-Host '请选择测试级别 (1-4)').Trim()) {
            '1' { $Concurrent = 20;  $Total = 200 }
            '2' { $Concurrent = 50;  $Total = 500 }
            '3' { $Concurrent = 100; $Total = 1000 }
            '4' { $Concurrent = 200; $Total = 2000 }
            default {
                Write-Host '无效选择，使用默认中等检查' -ForegroundColor Yellow
                $Concurrent = 50; $Total = 500
            }
        }
    }
    if ($Concurrent -lt 1) { $Concurrent = 1 }
    if ($Total -lt 1) { $Total = 1 }

    $url    = $ServerUrl + $ep.Path
    $method = $ep.Method
    $body   = ''
    if ($method -eq 'POST') { $body = New-GipfelLoginBody -User $auth.User -Pass $auth.Pass }

    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host '                    测试配置'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host (" 服务器:   {0}" -f $ServerUrl)
    Write-Host (" 端点:     {0} ({1})" -f $ep.Path, $ep.Name)
    Write-Host (" 方法:     {0}" -f $method)
    Write-Host (" 并发数:   {0}" -f $Concurrent)
    Write-Host (" 总请求数: {0}" -f $Total)
    if ($auth.Token) { Write-Host ' 认证:     Bearer Token 已设置' }
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''
    $go = (Read-Host '是否开始测试? (y/n)').Trim()
    if ($go -notmatch '^[Yy]') {
        Write-Host '测试已取消' -ForegroundColor Yellow
        return
    }

    Write-Host ''
    Write-Host ("正在执行 {0} 并发测试 ({1})，请稍候..." -f $Concurrent, $ep.Name) -ForegroundColor Cyan

    $r = Invoke-GipfelLoad -Url $url -Method $method -Body $body -Token $auth.Token `
                           -Concurrent $Concurrent -Total $Total -TimeoutSec 30

    $rate = if ($r.Total -gt 0) { $r.Success / $r.Total * 100 } else { 0 }

    # ---------------- 评分 ----------------
    $score = 0
    if     ($r.Rps -ge 300) { $score += 30 } elseif ($r.Rps -ge 200) { $score += 25 } elseif ($r.Rps -ge 100) { $score += 20 }
    if     ($r.Avg -le 100) { $score += 30 } elseif ($r.Avg -le 300) { $score += 25 } elseif ($r.Avg -le 500) { $score += 15 }
    if     ($rate   -ge 99) { $score += 30 } elseif ($rate   -ge 95) { $score += 20 } elseif ($rate   -ge 90) { $score += 10 }
    if     ($r.P95  -le 500) { $score += 10 } elseif ($r.P95 -le 1000) { $score += 5 }

    $rating = if     ($score -ge 90) { 'A+ (优秀)' }
              elseif ($score -ge 80) { 'A (良好)' }
              elseif ($score -ge 70) { 'B (中等)' }
              elseif ($score -ge 60) { 'C (及格)' }
              else                   { 'D (需优化)' }
    $scoreColor = if ($score -ge 80) { 'Green' } elseif ($score -ge 60) { 'Yellow' } else { 'Red' }

    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host '                    测试结果'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''
    Write-Host (" 目标端点:     {0} ({1})" -f $ep.Path, $ep.Name)
    Write-Host (" 请求方法:     {0}" -f $method)
    Write-Host (" 总请求数:     {0}" -f $r.Total)
    Write-Host (" 成功请求:     {0}" -f $r.Success) -ForegroundColor Green
    Write-Host (" 失败请求:     {0}" -f $r.Fail) -ForegroundColor $(if ($r.Fail -gt 0) { 'Red' } else { 'Green' })
    Write-Host (" 成功率:       {0}%" -f [Math]::Round($rate, 2)) -ForegroundColor $(if ($rate -ge 95) { 'Green' } else { 'Red' })
    Write-Host (" 总耗时:       {0} 秒" -f [Math]::Round($r.Seconds, 2))
    Write-Host (" 每秒请求数:   {0} RPS" -f [Math]::Round($r.Rps, 2)) -ForegroundColor Cyan
    Write-Host ''
    Write-Host ' 响应时间统计:' -ForegroundColor Yellow
    Write-Host ("   最小值:     {0} ms" -f $r.Min)
    Write-Host ("   最大值:     {0} ms" -f $r.Max) -ForegroundColor $(if ($r.Max -gt 2000) { 'Red' } else { 'Green' })
    Write-Host ("   平均值:     {0} ms" -f [Math]::Round($r.Avg, 2)) -ForegroundColor $(if ($r.Avg -gt 500) { 'Red' } else { 'Green' })
    Write-Host ("   P50:        {0} ms" -f $r.P50)
    Write-Host ("   P95:        {0} ms" -f $r.P95) -ForegroundColor $(if ($r.P95 -gt 1000) { 'Red' } else { 'Green' })
    Write-Host ("   P99:        {0} ms" -f $r.P99)
    Write-Host ''
    Write-Host ' 状态码分布:' -ForegroundColor Yellow
    foreach ($code in ($r.Codes.Keys | Sort-Object)) {
        $label = if ($code -eq 0) { '连接失败/超时' } else { [string]$code }
        $color = if ($code -ge 200 -and $code -lt 300) { 'Green' } elseif ($code -eq 0) { 'Red' } else { 'Yellow' }
        Write-Host ("   {0,-16} {1} 次" -f $label, $r.Codes[$code]) -ForegroundColor $color
        # 非 2xx 时把后端返回的原因一并打出来（光看状态码分不清原因）
        if ($code -ne 0 -and ($code -lt 200 -or $code -ge 300)) {
            $why = Get-GipfelCodeReason -Result $r -Code $code
            if ($why) { Write-Host ("        └─ {0}" -f $why) -ForegroundColor DarkGray }
        }
    }
    Write-Host ''
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host '                    性能评估'
    Write-Host ('=' * 60) -ForegroundColor Cyan
    Write-Host ''
    Write-Host (" 综合评分: {0} / 100  ({1})" -f $score, $rating) -ForegroundColor $scoreColor
    Write-Host ''
    Write-Host ' 并发能力评估:' -ForegroundColor Yellow
    if ($r.Rps -ge 200 -and $rate -ge 95) {
        Write-Host ("   [OK] 服务器可稳定支持 {0} 并发" -f $Concurrent) -ForegroundColor Green
    } elseif ($r.Rps -ge 100 -and $rate -ge 90) {
        Write-Host ("   [~]  服务器可勉强支持 {0} 并发" -f $Concurrent) -ForegroundColor Yellow
    } else {
        Write-Host ("   [X]  服务器无法稳定支持 {0} 并发" -f $Concurrent) -ForegroundColor Red
    }
    Write-Host ''
    Write-Host ' 快速优化建议:' -ForegroundColor Yellow
    $tips = 0
    if ($r.Rps -lt 200)      { $tips++; Write-Host '   1. 增加 Daphne worker 数量' }
    if ($r.Avg -gt 300)      { $tips++; Write-Host '   2. 检查数据库查询性能 / 索引' }
    if ($r.Fail -gt 0)       { $tips++; Write-Host '   3. 查看服务器日志定位失败原因' }
    if ($r.P95 -gt 1000)     { $tips++; Write-Host '   4. 考虑添加 Redis 缓存' }
    if ($tips -eq 0)         { Write-Host '   各项指标良好，无需调整' -ForegroundColor Green }
    Write-Host ''

    # ---------------- 保存 ----------------
    if (-not $NoSave) {
        $dir   = Get-GipfelResultDir -ScriptRoot $PSScriptRoot
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $base  = Join-Path $dir ("quick-test-$stamp")

        $lines = @()
        $lines += ('=' * 60)
        $lines += 'Gipfel 快速高并发测试报告'
        $lines += ('=' * 60)
        $lines += ("测试时间: {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
        $lines += ("服务器:   {0}" -f $ServerUrl)
        $lines += ("端点:     {0} ({1})" -f $ep.Path, $ep.Name)
        $lines += ("方法:     {0}" -f $method)
        $lines += ("并发数:   {0}" -f $Concurrent)
        $lines += ("请求数:   {0}" -f $r.Total)
        $lines += ''
        $lines += '测试结果:'
        $lines += ("  成功:   {0}" -f $r.Success)
        $lines += ("  失败:   {0}" -f $r.Fail)
        $lines += ("  成功率: {0}%" -f [Math]::Round($rate, 2))
        $lines += ("  总耗时: {0} 秒" -f [Math]::Round($r.Seconds, 2))
        $lines += ("  RPS:    {0}" -f [Math]::Round($r.Rps, 2))
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
            $lines += ("  {0}: {1} 次" -f $label, $r.Codes[$code])
        }
        $lines += ''
        $lines += ("综合评分: {0} / 100 ({1})" -f $score, $rating)
        $lines += ('=' * 60)

        $lines | Out-File -FilePath "$base.txt" -Encoding UTF8

        $csv = for ($i = 0; $i -lt $r.Latencies.Length; $i++) {
            [pscustomobject]@{ 序号 = $i + 1; 响应时间ms = $r.Latencies[$i] }
        }
        $csv | Export-Csv -Path "$base.csv" -NoTypeInformation -Encoding UTF8

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
