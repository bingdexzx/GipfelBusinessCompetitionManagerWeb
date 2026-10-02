@echo off
chcp 65001 >nul
setlocal

echo.
echo ============================================================
echo        Gipfel 高并发压力测试工具
echo ============================================================
echo.

:: ==================== 服务器地址 ====================
echo 请输入服务器地址
echo 示例: http://123.456.789.0 或 http://your-domain.com
echo.
set /p "SERVER_URL=服务器地址: "

if "%SERVER_URL%"=="" (
    echo.
    echo 错误：服务器地址不能为空！
    echo.
    pause
    exit /b 1
)

:: 移除末尾斜杠
if "%SERVER_URL:~-1%"=="/" set "SERVER_URL=%SERVER_URL:~0,-1%"

echo.
echo 你输入的地址是: %SERVER_URL%
echo.

:: ==================== 测试类型 ====================
echo 请选择测试类型:
echo.
echo   1 - 快速测试 (10并发, 100请求)
echo   2 - 标准测试 (50并发, 500请求)
echo   3 - 压力测试 (100并发, 1000请求)
echo   4 - 高并发测试 (200并发, 2000请求)
echo.
set /p "CHOICE=请输入数字 (1-4): "

if "%CHOICE%"=="1" (
    set "CONCURRENT=10"
    set "TOTAL=100"
) else if "%CHOICE%"=="2" (
    set "CONCURRENT=50"
    set "TOTAL=500"
) else if "%CHOICE%"=="3" (
    set "CONCURRENT=100"
    set "TOTAL=1000"
) else if "%CHOICE%"=="4" (
    set "CONCURRENT=200"
    set "TOTAL=2000"
) else (
    echo.
    echo 无效选择，使用默认: 50并发, 500请求
    set "CONCURRENT=50"
    set "TOTAL=500"
)

:: ==================== 测试端点 ====================
echo.
echo 请选择测试端点:
echo.
echo   1. /api/health          - 健康检查 (轻量级, 无需认证)
echo   2. /api/version         - 版本信息 (轻量级, 无需认证)
echo   3. /api/auth/login      - 用户登录 (中等, POST, 无需认证)
echo   4. /api/competitions    - 比赛列表 (中等, 需认证)
echo   5. /api/companies       - 公司列表 (中等, 需认证)
echo   6. /api/materials       - 原料列表 (中等, 需认证)
echo   7. /api/regions         - 区域列表 (中等, 需认证)
echo   8. /api/stocks          - 股票数据 (较高, 需认证)
echo   9. /api/maps/full       - 地图数据 (较高, 需认证)
echo.
set /p "EP_CHOICE=请输入数字 (1-9): "

:: 初始化变量
set "METHOD=GET"
set "TOKEN="
set "LOGIN_USER="
set "LOGIN_PASS="
set "NEED_AUTH=0"
set "EP_NAME="

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
    echo 无效选择，使用默认: /api/health
    set "ENDPOINT=/api/health"
    set "EP_NAME=健康检查"
)

:: ==================== 认证 Token ====================
if "%NEED_AUTH%"=="1" (
    echo.
    echo 此端点需要认证，请输入 Bearer Token:
    echo (可从浏览器开发者工具 Network 面板复制 Authorization 请求头)
    echo.
    set /p "TOKEN=Token: "
    if "!TOKEN!"=="" (
        echo.
        echo [警告] 未提供 Token，测试可能返回 401 错误
    )
)

:: ==================== POST 登录凭据 ====================
if "%METHOD%"=="POST" (
    echo.
    echo 请输入登录凭据:
    echo.
    set /p "LOGIN_USER=用户名: "
    set /p "LOGIN_PASS=密码: "
    if "!LOGIN_USER!"=="" (
        echo.
        echo [警告] 未提供用户名，测试可能返回 400 错误
    )
)

:: ==================== 配置摘要 ====================
echo.
echo ============================================================
echo 测试配置
echo ============================================================
echo 服务器:   %SERVER_URL%
echo 端点:     %ENDPOINT% (%EP_NAME%)
echo 方法:     %METHOD%
echo 并发数:   %CONCURRENT%
echo 请求数:   %TOTAL%
if defined TOKEN echo 认证:     Bearer Token 已设置
if defined LOGIN_USER echo 登录用户: %LOGIN_USER%
echo ============================================================
echo.
echo 按任意键开始测试...
pause >nul

echo.
echo 正在测试 %EP_NAME% (%ENDPOINT%)，请稍候...
echo.

:: ==================== 生成并执行测试 ====================
set "PS_FILE=%temp%\gipfel-stress-test.ps1"
call :write_ps1 > "%PS_FILE%"
powershell -ExecutionPolicy Bypass -File "%PS_FILE%"
del "%PS_FILE%" 2>nul

echo.
echo ============================================================
echo 测试完成！
echo ============================================================
echo.
pause
exit /b 0

:: ============================================================
:: 子程序：生成 PowerShell 压力测试脚本
:: 在子程序中每行独立解析，( ) { } 无需转义
:: 仅需转义: | → ^|   % → %%
:: ============================================================
:write_ps1
echo $url = '%SERVER_URL%%ENDPOINT%'
echo $method = '%METHOD%'
echo $concurrent = %CONCURRENT%
echo $total = %TOTAL%
echo $token = '%TOKEN%'
echo $username = '%LOGIN_USER%'
echo $password = '%LOGIN_PASS%'
echo.
echo # ==================== HttpClient 配置 ====================
echo $handler = New-Object System.Net.Http.HttpClientHandler
echo $handler.MaxConnectionsPerServer = $concurrent
echo $client = New-Object System.Net.Http.HttpClient($handler)
echo $client.Timeout = [TimeSpan]::FromSeconds(30)
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
echo $semaphore = New-Object System.Threading.SemaphoreSlim($concurrent, $concurrent)
echo $successCount = 0
echo $failCount = 0
echo $statusCodes = @{}
echo $responseTimes = New-Object System.Collections.Concurrent.ConcurrentBag[int]
echo.
echo $tasks = @()
echo $startTime = Get-Date
echo.
echo Write-Host "开始测试 $url ..." -ForegroundColor Cyan
echo Write-Host "并发: $concurrent  总请求: $total  方法: $method" -ForegroundColor Gray
echo Write-Host ''
echo.
echo for ($i = 1; $i -le $total; $i++) {
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
echo                 $code = [int]$response.StatusCode
echo                 if ($response.IsSuccessStatusCode) {
echo                     [System.Threading.Interlocked]::Increment([ref]$successCount) ^| Out-Null
echo                 } else {
echo                     [System.Threading.Interlocked]::Increment([ref]$failCount) ^| Out-Null
echo                 }
echo                 # 记录状态码
echo                 [System.Threading.Monitor]::Enter($statusCodes)
echo                 try {
echo                     if ($statusCodes.ContainsKey($code)) { $statusCodes[$code]++ } else { $statusCodes[$code] = 1 }
echo                 } finally {
echo                     [System.Threading.Monitor]::Exit($statusCodes)
echo                 }
echo                 $response.Dispose()
echo             } catch {
echo                 $sw.Stop()
echo                 [System.Threading.Interlocked]::Increment([ref]$failCount) ^| Out-Null
echo                 [System.Threading.Monitor]::Enter($statusCodes)
echo                 try {
echo                     if ($statusCodes.ContainsKey(0)) { $statusCodes[0]++ } else { $statusCodes[0] = 1 }
echo                 } finally {
echo                     [System.Threading.Monitor]::Exit($statusCodes)
echo                 }
echo             }
echo             $responseTimes.Add([int]$sw.ElapsedMilliseconds)
echo         } finally {
echo             $semaphore.Release() ^| Out-Null
echo         }
echo     })
echo     $tasks += $task
echo }
echo.
echo [System.Threading.Tasks.Task]::WaitAll($tasks)
echo $endTime = Get-Date
echo.
echo # ==================== 统计结果 ====================
echo $totalSeconds = ($endTime - $startTime).TotalSeconds
echo $avgTime = if ($responseTimes.Count -gt 0) { ($responseTimes ^| Measure-Object -Average).Average } else { 0 }
echo $rps = $total / $totalSeconds
echo $successRate = ($successCount / $total) * 100
echo.
echo $sorted = $responseTimes ^| Sort-Object
echo $min = if ($sorted.Count -gt 0) { $sorted[0] } else { 0 }
echo $max = if ($sorted.Count -gt 0) { $sorted[-1] } else { 0 }
echo $p50 = if ($sorted.Count -gt 0) { $sorted[[Math]::Floor($sorted.Count * 0.5)] } else { 0 }
echo $p95 = if ($sorted.Count -gt 0) { $sorted[[Math]::Floor($sorted.Count * 0.95)] } else { 0 }
echo $p99 = if ($sorted.Count -gt 0) { $sorted[[Math]::Floor($sorted.Count * 0.99)] } else { 0 }
echo.
echo # ==================== 输出报告 ====================
echo Write-Host ''
echo Write-Host '============================================================' -ForegroundColor Cyan
echo Write-Host '                    测试结果' -ForegroundColor Cyan
echo Write-Host '============================================================' -ForegroundColor Cyan
echo Write-Host ''
echo Write-Host "目标端点:     $url"
echo Write-Host "请求方法:     $method"
echo Write-Host "总请求数:     $total"
echo Write-Host "成功请求:     $successCount" -ForegroundColor Green
echo Write-Host "失败请求:     $failCount" -ForegroundColor $(if ($failCount -gt 0) {'Red'} else {'Green'})
echo Write-Host "成功率:       $([Math]::Round($successRate, 2))%%" -ForegroundColor $(if ($successRate -ge 95) {'Green'} else {'Red'})
echo Write-Host "总耗时:       $([Math]::Round($totalSeconds, 2)) 秒"
echo Write-Host "每秒请求数:   $([Math]::Round($rps, 2)) RPS" -ForegroundColor Cyan
echo Write-Host ''
echo Write-Host '响应时间:' -ForegroundColor Yellow
echo Write-Host "  最小值:     $min ms"
echo Write-Host "  最大值:     $max ms" -ForegroundColor $(if ($max -gt 2000) {'Red'} else {'Green'})
echo Write-Host "  平均值:     $([Math]::Round($avgTime, 2)) ms" -ForegroundColor $(if ($avgTime -gt 500) {'Red'} else {'Green'})
echo Write-Host "  P50:        $p50 ms"
echo Write-Host "  P95:        $p95 ms" -ForegroundColor $(if ($p95 -gt 1000) {'Red'} else {'Green'})
echo Write-Host "  P99:        $p99 ms"
echo Write-Host ''
echo Write-Host '状态码分布:' -ForegroundColor Yellow
echo foreach ($code in ($statusCodes.Keys ^| Sort-Object)) {
echo     $color = if ($code -eq 200) { 'Green' } elseif ($code -eq 0) { 'Red' } else { 'Yellow' }
echo     $label = if ($code -eq 0) { '连接失败' } else { "$code" }
echo     Write-Host ("  {0}: {1} 次" -f $label, $statusCodes[$code]) -ForegroundColor $color
echo }
echo Write-Host ''
echo Write-Host '============================================================' -ForegroundColor Cyan
goto :eof
