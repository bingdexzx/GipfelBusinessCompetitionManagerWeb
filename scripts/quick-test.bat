@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================================
:: Gipfel 快速高并发检查工具
:: 用于快速验证服务器高并发能力
:: ============================================================

title Gipfel 快速高并发检查工具

echo.
echo [96m============================================================[0m
echo [96m       Gipfel 快速高并发检查工具[0m
echo [96m============================================================[0m
echo.

:: 获取服务器地址
set /p "SERVER_URL=请输入服务器地址 (例如: http://your-domain.com): "
if "!SERVER_URL!"=="" (
    echo [91m错误：服务器地址不能为空！[0m
    pause
    exit /b 1
)

:: 移除末尾斜杠
if "!SERVER_URL:~-1!"=="/" set "SERVER_URL=!SERVER_URL:~0,-1!"

echo.
echo [94m请选择测试级别：[0m
echo [92m1. 快速检查%RESET% (20并发, 200请求)
echo [92m2. 中等检查%RESET% (50并发, 500请求)
echo [92m3. 高并发检查%RESET% (100并发, 1000请求)
echo [92m4. 超高并发检查%RESET% (200并发, 2000请求)
echo.

set /p "LEVEL=请选择测试级别 (1-4): "

if "!LEVEL!"=="1" (
    set "CONCURRENT=20"
    set "TOTAL=200"
) else if "!LEVEL!"=="2" (
    set "CONCURRENT=50"
    set "TOTAL=500"
) else if "!LEVEL!"=="3" (
    set "CONCURRENT=100"
    set "TOTAL=1000"
) else if "!LEVEL!"=="4" (
    set "CONCURRENT=200"
    set "TOTAL=2000"
) else (
    echo [91m无效选择，使用默认中等检查[0m
    set "CONCURRENT=50"
    set "TOTAL=500"
)

echo.
echo [96m============================================================[0m
echo [96m                    测试配置[0m
echo [96m============================================================[0m
echo.
echo [93m服务器地址：[0m !SERVER_URL!
echo [93m测试端点：[0m /api/health
echo [93m并发数：[0m !CONCURRENT!
echo [93m总请求数：[0m !TOTAL!
echo.

set /p "CONFIRM=是否开始测试? (y/n): "
if /i not "!CONFIRM!"=="y" (
    echo [93m测试已取消[0m
    pause
    exit /b 0
)

echo.
echo [94m正在执行 !CONCURRENT! 并发测试，请稍候...[0m
echo.

:: 使用 PowerShell 进行高并发测试
powershell -ExecutionPolicy Bypass -Command "& {
    $ErrorActionPreference = 'Continue'
    
    $url = '!SERVER_URL!/api/health'
    $concurrent = !CONCURRENT!
    $total = !TOTAL!
    
    # 结果统计
    $results = [System.Collections.Concurrent.ConcurrentBag[PSObject]]::new()
    $successCount = 0
    $failCount = 0
    $responseTimes = [System.Collections.Concurrent.ConcurrentBag[int]]::new()
    
    # 使用 .NET HttpClient
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.MaxConnectionsPerServer = $concurrent
    $handler.UseCookies = $false
    
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(30)
    $client.DefaultRequestHeaders.ConnectionClose = $false
    
    $semaphore = [System.Threading.SemaphoreSlim]::new($concurrent, $concurrent)
    $progress = 0
    
    $tasks = @()
    $startTime = [System.Diagnostics.Stopwatch]::StartNew()
    
    Write-Host '开始执行 $total 个请求（并发: $concurrent）...' -ForegroundColor Cyan
    
    for ($i = 1; $i -le $total; $i++) {
        $taskId = $i
        $task = [System.Threading.Tasks.Task]::Run([Action]{
            $semaphore.Wait() | Out-Null
            try {
                $sw = [System.Diagnostics.Stopwatch]::StartNew()
                
                try {
                    $response = $client.GetAsync($url).Result
                    $sw.Stop()
                    $responseTime = [int]$sw.ElapsedMilliseconds
                    
                    $result = [PSCustomObject]@{
                        Id = $taskId
                        StatusCode = [int]$response.StatusCode
                        ResponseTime = $responseTime
                        Success = $response.IsSuccessStatusCode
                    }
                    
                    $response.Dispose()
                } catch {
                    $sw.Stop()
                    $result = [PSCustomObject]@{
                        Id = $taskId
                        StatusCode = 0
                        ResponseTime = [int]$sw.ElapsedMilliseconds
                        Success = $false
                    }
                }
                
                $results.Add($result)
                
                if ($result.Success) {
                    [System.Threading.Interlocked]::Increment([ref]$successCount) | Out-Null
                } else {
                    [System.Threading.Interlocked]::Increment([ref]$failCount) | Out-Null
                }
                
                $responseTimes.Add($result.ResponseTime)
                
                $current = [System.Threading.Interlocked]::Increment([ref]$progress)
                if ($current % 100 -eq 0) {
                    Write-Host '  已完成: $current / $total' -ForegroundColor Yellow
                }
            } finally {
                $semaphore.Release() | Out-Null
            }
        })
        $tasks += $task
    }
    
    [System.Threading.Tasks.Task]::WaitAll($tasks)
    $startTime.Stop()
    
    $totalSeconds = $startTime.Elapsed.TotalSeconds
    $avgTime = if ($responseTimes.Count -gt 0) { ($responseTimes | Measure-Object -Average).Average } else { 0 }
    $rps = if ($totalSeconds -gt 0) { $total / $totalSeconds } else { 0 }
    $successRate = ($successCount / $total) * 100
    
    if ($responseTimes.Count -gt 0) {
        $sortedTimes = $responseTimes | Sort-Object
        $minTime = $sortedTimes[0]
        $maxTime = $sortedTimes[-1]
        $p50 = $sortedTimes[[Math]::Floor($sortedTimes.Count * 0.5)]
        $p95 = $sortedTimes[[Math]::Floor($sortedTimes.Count * 0.95)]
        $p99 = $sortedTimes[[Math]::Floor($sortedTimes.Count * 0.99)]
    } else {
        $minTime = 0
        $maxTime = 0
        $p50 = 0
        $p95 = 0
        $p99 = 0
    }
    
    # 计算评分
    $score = 0
    if ($rps -ge 300) { $score += 30 }
    elseif ($rps -ge 200) { $score += 25 }
    elseif ($rps -ge 100) { $score += 20 }
    
    if ($avgTime -le 100) { $score += 30 }
    elseif ($avgTime -le 300) { $score += 25 }
    elseif ($avgTime -le 500) { $score += 15 }
    
    if ($successRate -ge 99) { $score += 30 }
    elseif ($successRate -ge 95) { $score += 20 }
    elseif ($successRate -ge 90) { $score += 10 }
    
    if ($p95 -le 500) { $score += 10 }
    elseif ($p95 -le 1000) { $score += 5 }
    
    # 输出结果
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                    测试结果' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '总请求数:     $total' -ForegroundColor Yellow
    Write-Host '成功请求:     $successCount' -ForegroundColor Green
    Write-Host '失败请求:     $failCount' -ForegroundColor $(if($failCount -gt 0){'Red'}else{'Green'})
    Write-Host '成功率:       $([Math]::Round($successRate, 2))%' -ForegroundColor $(if($successRate -ge 95){'Green'}else{'Red'})
    Write-Host '总耗时:       $([Math]::Round($totalSeconds, 2)) 秒' -ForegroundColor Yellow
    Write-Host '每秒请求数:   $([Math]::Round($rps, 2)) RPS' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '响应时间统计:' -ForegroundColor Yellow
    Write-Host '  最小值:     $minTime ms' -ForegroundColor Green
    Write-Host '  最大值:     $maxTime ms' -ForegroundColor $(if($maxTime -gt 2000){'Red'}else{'Green'})
    Write-Host '  平均值:     $([Math]::Round($avgTime, 2)) ms' -ForegroundColor $(if($avgTime -gt 500){'Red'}else{'Green'})
    Write-Host '  P50:        $p50 ms' -ForegroundColor $(if($p50 -gt 300){'Red'}else{'Green'})
    Write-Host '  P95:        $p95 ms' -ForegroundColor $(if($p95 -gt 1000){'Red'}else{'Green'})
    Write-Host '  P99:        $p99 ms' -ForegroundColor $(if($p99 -gt 2000){'Red'}else{'Green'})
    Write-Host ''
    
    # 性能评级
    $color = if ($score -ge 80) { 'Green' } elseif ($score -ge 60) { 'Yellow' } else { 'Red' }
    $rating = if ($score -ge 90) { 'A+ (优秀)' } elseif ($score -ge 80) { 'A (良好)' } elseif ($score -ge 70) { 'B (中等)' } elseif ($score -ge 60) { 'C (及格)' } else { 'D (需优化)' }
    
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                    性能评估' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '综合评分: $score / 100 ($rating)' -ForegroundColor $color
    Write-Host ''
    
    # 并发能力评估
    Write-Host '并发能力评估:' -ForegroundColor Yellow
    if ($rps -ge 200 -and $successRate -ge 95) {
        Write-Host '  ✓ 服务器可稳定支持 $concurrent 并发' -ForegroundColor Green
        Write-Host '  建议: 可以尝试更高并发测试' -ForegroundColor White
    } elseif ($rps -ge 100 -and $successRate -ge 90) {
        Write-Host '  △ 服务器可勉强支持 $concurrent 并发' -ForegroundColor Yellow
        Write-Host '  建议: 优化后可提升并发能力' -ForegroundColor White
    } else {
        Write-Host '  ✗ 服务器无法稳定支持 $concurrent 并发' -ForegroundColor Red
        Write-Host '  建议: 降低并发数或优化服务器配置' -ForegroundColor White
    }
    Write-Host ''
    
    # 快速建议
    Write-Host '快速优化建议:' -ForegroundColor Yellow
    if ($rps -lt 200) {
        Write-Host '  1. 增加 Daphne worker 数量' -ForegroundColor White
        Write-Host '  2. 启用 Nginx 缓冲和压缩' -ForegroundColor White
    }
    if ($avgTime -gt 300) {
        Write-Host '  3. 检查数据库查询性能' -ForegroundColor White
        Write-Host '  4. 考虑添加 Redis 缓存' -ForegroundColor White
    }
    if ($failCount -gt 0) {
        Write-Host '  5. 检查服务器日志' -ForegroundColor White
        Write-Host '  6. 增加服务器资源' -ForegroundColor White
    }
    Write-Host ''
    
    # 保存结果到文件
    $resultDir = 'scripts\test-results'
    if (!(Test-Path $resultDir)) {
        New-Item -ItemType Directory -Path $resultDir | Out-Null
    }
    
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $resultFile = Join-Path $resultDir \"quick-test-$timestamp.txt\"
    
    $summary = @'
============================================================
Gipfel 快速高并发测试报告
============================================================
测试时间: $(Get-Date)
服务器地址: !SERVER_URL!
测试端点: /api/health
并发数: $concurrent
总请求数: $total

测试结果:
  成功: $successCount / $total ($([Math]::Round($successRate, 2))%)
  失败: $failCount
  总耗时: $([Math]::Round($totalSeconds, 2)) 秒
  RPS: $([Math]::Round($rps, 2))

响应时间:
  最小: $minTime ms
  最大: $maxTime ms
  平均: $([Math]::Round($avgTime, 2)) ms
  P50: $p50 ms
  P95: $p95 ms
  P99: $p99 ms

综合评分: $score / 100 ($rating)
============================================================
'@
    
    $summary | Out-File -FilePath $resultFile -Encoding UTF8
    
    Write-Host '详细报告已保存到: $resultFile' -ForegroundColor Green
    Write-Host ''
}"

echo.
echo [96m============================================================[0m
echo [96m                    测试完成[0m
echo [96m============================================================[0m
echo.

pause
exit /b 0