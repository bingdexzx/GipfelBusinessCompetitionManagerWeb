@echo off
chcp 65001 >nul
setlocal

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

:: ==================== 服务器地址 ====================
set /p "SERVER_URL=请输入服务器地址 (例如: http://your-domain.com): "
if "%SERVER_URL%"=="" (
    echo [91m错误：服务器地址不能为空！[0m
    pause
    exit /b 1
)

:: 移除末尾斜杠
if "%SERVER_URL:~-1%"=="/" set "SERVER_URL=%SERVER_URL:~0,-1%"

:: ==================== 测试端点 ====================
echo.
echo [94m请选择测试端点：[0m
echo.
echo [92m  1.[0m /api/health          - 健康检查 (轻量级, 无需认证)
echo [92m  2.[0m /api/version         - 版本信息 (轻量级, 无需认证)
echo [92m  3.[0m /api/auth/login      - 用户登录 (POST, 无需认证)
echo [92m  4.[0m /api/competitions    - 比赛列表 (需认证)
echo [92m  5.[0m /api/companies       - 公司列表 (需认证)
echo [92m  6.[0m /api/materials       - 原料列表 (需认证)
echo [92m  7.[0m /api/regions         - 区域列表 (需认证)
echo [92m  8.[0m /api/stocks          - 股票数据 (需认证)
echo [92m  9.[0m /api/maps/full       - 地图数据 (需认证)
echo.

set /p "EP_CHOICE=请选择端点 (1-9): "

:: 初始化变量
set "METHOD=GET"
set "TOKEN="
set "LOGIN_USER="
set "LOGIN_PASS="
set "NEED_AUTH=0"

if "%EP_CHOICE%"=="1" (
    set "ENDPOINT=/api/health"
    set "EP_NAME=健康检查"
) else if "%EP_CHOICE%"=="2" (
    set "ENDPOINT=/api/version"
    set "EP_NAME=版本信息"
) else if "%EP_CHOICE%"=="3" (
    set "ENDPOINT=/api/auth/login"
    set "METHOD=POST"
    set "EP_NAME=用户登录"
) else if "%EP_CHOICE%"=="4" (
    set "ENDPOINT=/api/competitions"
    set "NEED_AUTH=1"
    set "EP_NAME=比赛列表"
) else if "%EP_CHOICE%"=="5" (
    set "ENDPOINT=/api/companies"
    set "NEED_AUTH=1"
    set "EP_NAME=公司列表"
) else if "%EP_CHOICE%"=="6" (
    set "ENDPOINT=/api/materials"
    set "NEED_AUTH=1"
    set "EP_NAME=原料列表"
) else if "%EP_CHOICE%"=="7" (
    set "ENDPOINT=/api/regions"
    set "NEED_AUTH=1"
    set "EP_NAME=区域列表"
) else if "%EP_CHOICE%"=="8" (
    set "ENDPOINT=/api/stocks"
    set "NEED_AUTH=1"
    set "EP_NAME=股票数据"
) else if "%EP_CHOICE%"=="9" (
    set "ENDPOINT=/api/maps/full"
    set "NEED_AUTH=1"
    set "EP_NAME=地图数据"
) else (
    echo [91m无效选择，使用默认: /api/health[0m
    set "ENDPOINT=/api/health"
    set "EP_NAME=健康检查"
)

:: ==================== 认证 Token ====================
if "%NEED_AUTH%"=="1" (
    echo.
    echo [93m此端点需要认证，请输入 Bearer Token:[0m
    echo [93m(可从浏览器开发者工具 Network 面板复制 Authorization 请求头)[0m
    echo.
    set /p "TOKEN=Token: "
    if "!TOKEN!"=="" (
        echo [91m[警告] 未提供 Token，测试可能返回 401 错误[0m
    )
)

:: ==================== POST 登录凭据 ====================
if "%METHOD%"=="POST" (
    echo.
    echo [93m请输入登录凭据:[0m
    echo.
    set /p "LOGIN_USER=用户名: "
    set /p "LOGIN_PASS=密码: "
    if "!LOGIN_USER!"=="" (
        echo [91m[警告] 未提供用户名，测试可能返回 400 错误[0m
    )
)

:: ==================== 测试级别 ====================
echo.
echo [94m请选择测试级别：[0m
echo [92m1. 快速检查[0m (20并发, 200请求)
echo [92m2. 中等检查[0m (50并发, 500请求)
echo [92m3. 高并发检查[0m (100并发, 1000请求)
echo [92m4. 超高并发检查[0m (200并发, 2000请求)
echo.

set /p "LEVEL=请选择测试级别 (1-4): "

if "%LEVEL%"=="1" (
    set "CONCURRENT=20"
    set "TOTAL=200"
) else if "%LEVEL%"=="2" (
    set "CONCURRENT=50"
    set "TOTAL=500"
) else if "%LEVEL%"=="3" (
    set "CONCURRENT=100"
    set "TOTAL=1000"
) else if "%LEVEL%"=="4" (
    set "CONCURRENT=200"
    set "TOTAL=2000"
) else (
    echo [91m无效选择，使用默认中等检查[0m
    set "CONCURRENT=50"
    set "TOTAL=500"
)

:: ==================== 配置摘要 ====================
echo.
echo [96m============================================================[0m
echo [96m                    测试配置[0m
echo [96m============================================================[0m
echo.
echo [93m服务器地址：[0m %SERVER_URL%
echo [93m测试端点：[0m   %ENDPOINT% (%EP_NAME%)
echo [93m请求方法：[0m   %METHOD%
echo [93m并发数：[0m     %CONCURRENT%
echo [93m总请求数：[0m   %TOTAL%
if defined TOKEN echo [93m认证：[0m       Bearer Token 已设置
if defined LOGIN_USER echo [93m登录用户：[0m %LOGIN_USER%
echo.

set /p "CONFIRM=是否开始测试? (y/n): "
if /i not "%CONFIRM%"=="y" (
    echo [93m测试已取消[0m
    pause
    exit /b 0
)

echo.
echo [94m正在执行 %CONCURRENT% 并发测试 (%EP_NAME%)，请稍候...[0m
echo.

:: ==================== 生成并执行测试 ====================
set "PS_FILE=%temp%\gipfel-quick-test.ps1"
call :write_ps1 > "%PS_FILE%"
powershell -ExecutionPolicy Bypass -File "%PS_FILE%"
del "%PS_FILE%" 2>nul

echo.
echo [96m============================================================[0m
echo [96m                    测试完成[0m
echo [96m============================================================[0m
echo.

pause
exit /b 0

:: ============================================================
:: 子程序：生成 PowerShell 快速测试脚本
:: 在子程序中每行独立解析，( ) { } 无需转义
:: 仅需转义: | → ^|   % → %%
:: ============================================================
:write_ps1
echo $ErrorActionPreference = 'Continue'
echo.
echo $url = '%SERVER_URL%%ENDPOINT%'
echo $method = '%METHOD%'
echo $concurrent = %CONCURRENT%
echo $total = %TOTAL%
echo $token = '%TOKEN%'
echo $username = '%LOGIN_USER%'
echo $password = '%LOGIN_PASS%'
echo $scriptDir = '%~dp0'
echo.
echo # ==================== HttpClient 配置 ====================
echo $handler = [System.Net.Http.HttpClientHandler]::new()
echo $handler.MaxConnectionsPerServer = $concurrent
echo $handler.UseCookies = $false
echo.
echo $client = [System.Net.Http.HttpClient]::new($handler)
echo $client.Timeout = [TimeSpan]::FromSeconds(30)
echo $client.DefaultRequestHeaders.ConnectionClose = $false
echo.
echo # 认证头
echo if ($token) {
echo     $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $token)
echo }
echo.
echo # POST 请求体
echo if ($method -eq 'POST' -and $username) {
echo     $postBody = '{"username":"' + $username + '","password":"' + $password + '"}'
echo }
echo.
echo # ==================== 并发测试 ====================
echo $results = [System.Collections.Concurrent.ConcurrentBag[PSObject]]::new()
echo $successCount = 0
echo $failCount = 0
echo $statusCodes = @{}
echo $responseTimes = [System.Collections.Concurrent.ConcurrentBag[int]]::new()
echo.
echo $semaphore = [System.Threading.SemaphoreSlim]::new($concurrent, $concurrent)
echo $progress = 0
echo $tasks = @()
echo $startTime = [System.Diagnostics.Stopwatch]::StartNew()
echo.
echo Write-Host "开始执行 $total 个请求（并发: $concurrent, 端点: $url）..." -ForegroundColor Cyan
echo.
echo for ($i = 1; $i -le $total; $i++) {
echo     $taskId = $i
echo     $task = [System.Threading.Tasks.Task]::Run({
echo         $semaphore.Wait() ^| Out-Null
echo         try {
echo             $sw = [System.Diagnostics.Stopwatch]::StartNew()
echo             try {
echo                 # 根据方法发送请求
echo                 if ($method -eq 'POST') {
echo                     $content = New-Object System.Net.Http.StringContent($postBody, [System.Text.Encoding]::UTF8, 'application/json')
echo                     $response = $client.PostAsync($url, $content).Result
echo                     $content.Dispose()
echo                 } else {
echo                     $response = $client.GetAsync($url).Result
echo                 }
echo                 $sw.Stop()
echo                 $responseTime = [int]$sw.ElapsedMilliseconds
echo                 $code = [int]$response.StatusCode
echo.
echo                 $result = [PSCustomObject]@{
echo                     Id = $taskId
echo                     StatusCode = $code
echo                     ResponseTime = $responseTime
echo                     Success = $response.IsSuccessStatusCode
echo                 }
echo                 $response.Dispose()
echo             } catch {
echo                 $sw.Stop()
echo                 $result = [PSCustomObject]@{
echo                     Id = $taskId
echo                     StatusCode = 0
echo                     ResponseTime = [int]$sw.ElapsedMilliseconds
echo                     Success = $false
echo                 }
echo             }
echo.
echo             $results.Add($result)
echo.
echo             if ($result.Success) {
echo                 [System.Threading.Interlocked]::Increment([ref]$successCount) ^| Out-Null
echo             } else {
echo                 [System.Threading.Interlocked]::Increment([ref]$failCount) ^| Out-Null
echo             }
echo.
echo             $responseTimes.Add($result.ResponseTime)
echo.
echo             # 记录状态码
echo             [System.Threading.Monitor]::Enter($statusCodes)
echo             try {
echo                 $c = $result.StatusCode
echo                 if ($statusCodes.ContainsKey($c)) { $statusCodes[$c]++ } else { $statusCodes[$c] = 1 }
echo             } finally {
echo                 [System.Threading.Monitor]::Exit($statusCodes)
echo             }
echo.
echo             $current = [System.Threading.Interlocked]::Increment([ref]$progress)
echo             if ($current %% 100 -eq 0) {
echo                 Write-Host "  已完成: $current / $total" -ForegroundColor Yellow
echo             }
echo         } finally {
echo             $semaphore.Release() ^| Out-Null
echo         }
echo     }.GetNewClosure())
echo     $tasks += $task
echo }
echo.
echo [System.Threading.Tasks.Task]::WaitAll($tasks)
echo $startTime.Stop()
echo.
echo # ==================== 统计结果 ====================
echo $totalSeconds = $startTime.Elapsed.TotalSeconds
echo $avgTime = if ($responseTimes.Count -gt 0) { ($responseTimes ^| Measure-Object -Average).Average } else { 0 }
echo $rps = if ($totalSeconds -gt 0) { $total / $totalSeconds } else { 0 }
echo $successRate = ($successCount / $total) * 100
echo.
echo if ($responseTimes.Count -gt 0) {
echo     $sortedTimes = $responseTimes ^| Sort-Object
echo     $minTime = $sortedTimes[0]
echo     $maxTime = $sortedTimes[-1]
echo     $p50 = $sortedTimes[[Math]::Floor($sortedTimes.Count * 0.5)]
echo     $p95 = $sortedTimes[[Math]::Floor($sortedTimes.Count * 0.95)]
echo     $p99 = $sortedTimes[[Math]::Floor($sortedTimes.Count * 0.99)]
echo } else {
echo     $minTime = 0
echo     $maxTime = 0
echo     $p50 = 0
echo     $p95 = 0
echo     $p99 = 0
echo }
echo.
echo # ==================== 评分 ====================
echo $score = 0
echo if ($rps -ge 300) { $score += 30 }
echo elseif ($rps -ge 200) { $score += 25 }
echo elseif ($rps -ge 100) { $score += 20 }
echo.
echo if ($avgTime -le 100) { $score += 30 }
echo elseif ($avgTime -le 300) { $score += 25 }
echo elseif ($avgTime -le 500) { $score += 15 }
echo.
echo if ($successRate -ge 99) { $score += 30 }
echo elseif ($successRate -ge 95) { $score += 20 }
echo elseif ($successRate -ge 90) { $score += 10 }
echo.
echo if ($p95 -le 500) { $score += 10 }
echo elseif ($p95 -le 1000) { $score += 5 }
echo.
echo # ==================== 输出结果 ====================
echo Write-Host ''
echo Write-Host '============================================================' -ForegroundColor Cyan
echo Write-Host '                    测试结果' -ForegroundColor Cyan
echo Write-Host '============================================================' -ForegroundColor Cyan
echo Write-Host ''
echo Write-Host "目标端点:     $url" -ForegroundColor Yellow
echo Write-Host "请求方法:     $method"
echo Write-Host "总请求数:     $total"
echo Write-Host "成功请求:     $successCount" -ForegroundColor Green
echo Write-Host "失败请求:     $failCount" -ForegroundColor $(if($failCount -gt 0){'Red'}else{'Green'})
echo Write-Host "成功率:       $([Math]::Round($successRate, 2))%%" -ForegroundColor $(if($successRate -ge 95){'Green'}else{'Red'})
echo Write-Host "总耗时:       $([Math]::Round($totalSeconds, 2)) 秒" -ForegroundColor Yellow
echo Write-Host "每秒请求数:   $([Math]::Round($rps, 2)) RPS" -ForegroundColor Cyan
echo Write-Host ''
echo Write-Host '响应时间统计:' -ForegroundColor Yellow
echo Write-Host "  最小值:     $minTime ms" -ForegroundColor Green
echo Write-Host "  最大值:     $maxTime ms" -ForegroundColor $(if($maxTime -gt 2000){'Red'}else{'Green'})
echo Write-Host "  平均值:     $([Math]::Round($avgTime, 2)) ms" -ForegroundColor $(if($avgTime -gt 500){'Red'}else{'Green'})
echo Write-Host "  P50:        $p50 ms" -ForegroundColor $(if($p50 -gt 300){'Red'}else{'Green'})
echo Write-Host "  P95:        $p95 ms" -ForegroundColor $(if($p95 -gt 1000){'Red'}else{'Green'})
echo Write-Host "  P99:        $p99 ms" -ForegroundColor $(if($p99 -gt 2000){'Red'}else{'Green'})
echo Write-Host ''
echo Write-Host '状态码分布:' -ForegroundColor Yellow
echo foreach ($code in ($statusCodes.Keys ^| Sort-Object)) {
echo     $color = if ($code -eq 200) { 'Green' } elseif ($code -eq 0) { 'Red' } else { 'Yellow' }
echo     $label = if ($code -eq 0) { '连接失败' } else { "$code" }
echo     Write-Host ("  {0}: {1} 次" -f $label, $statusCodes[$code]) -ForegroundColor $color
echo }
echo Write-Host ''
echo.
echo # ==================== 性能评级 ====================
echo $color = if ($score -ge 80) { 'Green' } elseif ($score -ge 60) { 'Yellow' } else { 'Red' }
echo $rating = if ($score -ge 90) { 'A+ (优秀)' } elseif ($score -ge 80) { 'A (良好)' } elseif ($score -ge 70) { 'B (中等)' } elseif ($score -ge 60) { 'C (及格)' } else { 'D (需优化)' }
echo.
echo Write-Host '============================================================' -ForegroundColor Cyan
echo Write-Host '                    性能评估' -ForegroundColor Cyan
echo Write-Host '============================================================' -ForegroundColor Cyan
echo Write-Host ''
echo Write-Host "综合评分: $score / 100 ($rating)" -ForegroundColor $color
echo Write-Host ''
echo.
echo # ==================== 并发能力评估 ====================
echo Write-Host '并发能力评估:' -ForegroundColor Yellow
echo if ($rps -ge 200 -and $successRate -ge 95) {
echo     Write-Host "  √ 服务器可稳定支持 $concurrent 并发" -ForegroundColor Green
echo     Write-Host '  建议: 可以尝试更高并发测试' -ForegroundColor White
echo } elseif ($rps -ge 100 -and $successRate -ge 90) {
echo     Write-Host "  ~ 服务器可勉强支持 $concurrent 并发" -ForegroundColor Yellow
echo     Write-Host '  建议: 优化后可提升并发能力' -ForegroundColor White
echo } else {
echo     Write-Host "  X 服务器无法稳定支持 $concurrent 并发" -ForegroundColor Red
echo     Write-Host '  建议: 降低并发数或优化服务器配置' -ForegroundColor White
echo }
echo Write-Host ''
echo.
echo # ==================== 优化建议 ====================
echo Write-Host '快速优化建议:' -ForegroundColor Yellow
echo if ($rps -lt 200) {
echo     Write-Host '  1. 增加 Daphne worker 数量' -ForegroundColor White
echo     Write-Host '  2. 启用 Nginx 缓冲和压缩' -ForegroundColor White
echo }
echo if ($avgTime -gt 300) {
echo     Write-Host '  3. 检查数据库查询性能' -ForegroundColor White
echo     Write-Host '  4. 考虑添加 Redis 缓存' -ForegroundColor White
echo }
echo if ($failCount -gt 0) {
echo     Write-Host '  5. 检查服务器日志' -ForegroundColor White
echo     Write-Host '  6. 增加服务器资源' -ForegroundColor White
echo }
echo Write-Host ''
echo.
echo # ==================== 保存结果 ====================
echo $resultDir = Join-Path $scriptDir 'test-results'
echo if (!(Test-Path $resultDir)) {
echo     New-Item -ItemType Directory -Path $resultDir ^| Out-Null
echo }
echo.
echo $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
echo $resultFile = Join-Path $resultDir "quick-test-$timestamp.txt"
echo.
echo $summary = @"
echo ============================================================
echo Gipfel 快速高并发测试报告
echo ============================================================
echo 测试时间: $(Get-Date)
echo 服务器地址: $url
echo 请求方法: $method
echo 并发数: $concurrent
echo 总请求数: $total
echo.
echo 测试结果:
echo   成功: $successCount / $total ($([Math]::Round($successRate, 2))%%)
echo   失败: $failCount
echo   总耗时: $([Math]::Round($totalSeconds, 2)) 秒
echo   RPS: $([Math]::Round($rps, 2))
echo.
echo 响应时间:
echo   最小: $minTime ms
echo   最大: $maxTime ms
echo   平均: $([Math]::Round($avgTime, 2)) ms
echo   P50: $p50 ms
echo   P95: $p95 ms
echo   P99: $p99 ms
echo.
echo 状态码分布:
echo foreach ($code in ($statusCodes.Keys ^| Sort-Object)) {
echo     $label = if ($code -eq 0) { '连接失败' } else { "$code" }
echo     "  $label`: $($statusCodes[$code]) 次"
echo }
echo.
echo 综合评分: $score / 100 ($rating)
echo ============================================================
echo "@
echo.
echo $summary ^| Out-File -FilePath $resultFile -Encoding UTF8
echo.
echo Write-Host "详细报告已保存到: $resultFile" -ForegroundColor Green
echo Write-Host ''
goto :eof
