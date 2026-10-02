@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================================
:: Gipfel 高并发压力测试工具
:: 专为高并发场景设计，支持 100-500 并发
:: ============================================================

title Gipfel 高并发压力测试工具

:: 颜色设置
set "GREEN=[92m"
set "RED=[91m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "CYAN=[96m"
set "MAGENTA=[95m"
set "RESET=[0m"

:: 显示欢迎信息
echo.
echo %CYAN%============================================================%RESET%
echo %CYAN%       Gipfel 高并发压力测试工具 v2.0%RESET%
echo %CYAN%============================================================%RESET%
echo.
echo %YELLOW%专为高并发场景设计，支持 100-500 并发测试%RESET%
echo %MAGENTA%⚠️  高并发测试可能对服务器造成压力，请确保在测试环境运行%RESET%
echo.

:: 获取服务器信息
echo %BLUE%请输入服务器信息：%RESET%
echo.

set /p "SERVER_URL=请输入服务器地址 (例如: http://your-domain.com): "
if "!SERVER_URL!"=="" (
    echo %RED%错误：服务器地址不能为空！%RESET%
    pause
    exit /b 1
)

:: 移除末尾斜杠
if "!SERVER_URL:~-1!"=="/" set "SERVER_URL=!SERVER_URL:~0,-1!"

echo.
echo %BLUE%高并发测试配置：%RESET%
echo --------------------------------------------------
echo %GREEN%1. 中等并发%RESET%     (100并发, 1000请求)
echo %GREEN%2. 高并发%RESET%       (150并发, 1500请求)
echo %GREEN%3. 超高并发%RESET%     (200并发, 2000请求)
echo %GREEN%4. 极限并发%RESET%     (300并发, 3000请求)
echo %GREEN%5. 疯狂并发%RESET%     (500并发, 5000请求)
echo %GREEN%6. 自定义高并发%RESET% (自定义并发数和请求数)
echo %GREEN%7. 渐进式测试%RESET%   (逐步增加并发，找到性能拐点)
echo.

set /p "TEST_CHOICE=请选择测试类型 (1-7): "

:: 根据选择设置参数
if "!TEST_CHOICE!"=="1" (
    set "CONCURRENT=100"
    set "TOTAL=1000"
    set "TEST_NAME=中等并发测试"
) else if "!TEST_CHOICE!"=="2" (
    set "CONCURRENT=150"
    set "TOTAL=1500"
    set "TEST_NAME=高并发测试"
) else if "!TEST_CHOICE!"=="3" (
    set "CONCURRENT=200"
    set "TOTAL=2000"
    set "TEST_NAME=超高并发测试"
) else if "!TEST_CHOICE!"=="4" (
    set "CONCURRENT=300"
    set "TOTAL=3000"
    set "TEST_NAME=极限并发测试"
) else if "!TEST_CHOICE!"=="5" (
    set "CONCURRENT=500"
    set "TOTAL=5000"
    set "TEST_NAME=疯狂并发测试"
) else if "!TEST_CHOICE!"=="6" (
    echo.
    echo %YELLOW%自定义高并发测试%RESET%
    set /p "CONCURRENT=请输入并发数 (建议: 100-500): "
    set /p "TOTAL=请输入总请求数 (建议: 并发数 x 10): "
    set "TEST_NAME=自定义高并发测试"
) else if "!TEST_CHOICE!"=="7" (
    echo.
    echo %YELLOW%渐进式测试模式%RESET%
    echo %YELLOW%将从 50 并发开始，每次增加 50，直到 300 并发%RESET%
    echo.
    set "PROGRESSIVE_TEST=1"
    set "CONCURRENT=50"
    set "TOTAL=500"
    set "TEST_NAME=渐进式测试"
) else (
    echo %RED%无效选择，使用默认超高并发测试%RESET%
    set "CONCURRENT=200"
    set "TOTAL=2000"
    set "TEST_NAME=超高并发测试"
)

:: 选择测试端点
echo.
echo %BLUE%选择测试端点：%RESET%
echo --------------------------------------------------
echo %GREEN%1. 健康检查%RESET%     (/api/health) - 轻量级，纯内存
echo %GREEN%2. 比赛列表%RESET%     (/api/competitions) - 数据库查询
echo %GREEN%3. 公司列表%RESET%     (/api/companies) - 关联查询
echo %GREEN%4. 股票数据%RESET%     (/api/stocks) - 复杂查询
echo %GREEN%5. 合同列表%RESET%     (/api/contracts) - 多表关联
echo %GREEN%6. 用户登录%RESET%     (/api/auth/login) - 认证+数据库
echo %GREEN%7. 自定义端点%RESET%
echo.

set /p "ENDPOINT_CHOICE=请选择测试端点 (1-7): "

if "!ENDPOINT_CHOICE!"=="1" (
    set "ENDPOINT=/api/health"
    set "ENDPOINT_NAME=健康检查"
) else if "!ENDPOINT_CHOICE!"=="2" (
    set "ENDPOINT=/api/competitions"
    set "ENDPOINT_NAME=比赛列表"
) else if "!ENDPOINT_CHOICE!"=="3" (
    set "ENDPOINT=/api/companies"
    set "ENDPOINT_NAME=公司列表"
) else if "!ENDPOINT_CHOICE!"=="4" (
    set "ENDPOINT=/api/stocks"
    set "ENDPOINT_NAME=股票数据"
) else if "!ENDPOINT_CHOICE!"=="5" (
    set "ENDPOINT=/api/contracts"
    set "ENDPOINT_NAME=合同列表"
) else if "!ENDPOINT_CHOICE!"=="6" (
    set "ENDPOINT=/api/auth/login"
    set "ENDPOINT_NAME=用户登录"
    set "REQUEST_METHOD=POST"
    set "REQUEST_DATA={\"username\":\"test\",\"password\":\"test123\"}"
) else if "!ENDPOINT_CHOICE!"=="7" (
    echo.
    set /p "ENDPOINT=请输入自定义端点 (例如: /api/custom): "
    set "ENDPOINT_NAME=自定义端点"
) else (
    echo %RED%无效选择，使用默认健康检查%RESET%
    set "ENDPOINT=/api/health"
    set "ENDPOINT_NAME=健康检查"
)

:: 检查是否需要认证
echo.
set /p "NEED_AUTH=是否需要认证令牌? (y/n): "
if /i "!NEED_AUTH!"=="y" (
    set /p "AUTH_TOKEN=请输入 Bearer Token: "
) else (
    set "AUTH_TOKEN="
)

:: 超时设置
echo.
echo %BLUE%超时设置：%RESET%
echo --------------------------------------------------
echo %GREEN%1. 默认%RESET% (30秒)
echo %GREEN%2. 宽松%RESET% (60秒)
echo %GREEN%3. 严格%RESET% (10秒)
echo %GREEN%4. 自定义%RESET%
echo.

set /p "TIMEOUT_CHOICE=请选择超时设置 (1-4): "

if "!TIMEOUT_CHOICE!"=="1" (
    set "TIMEOUT=30"
) else if "!TIMEOUT_CHOICE!"=="2" (
    set "TIMEOUT=60"
) else if "!TIMEOUT_CHOICE!"=="3" (
    set "TIMEOUT=10"
) else if "!TIMEOUT_CHOICE!"=="4" (
    set /p "TIMEOUT=请输入超时秒数: "
) else (
    set "TIMEOUT=30"
)

:: 显示测试配置
echo.
echo %CYAN%============================================================%RESET%
echo %CYAN%                    测试配置摘要%RESET%
echo %CYAN%============================================================%RESET%
echo.
echo %YELLOW%测试类型：%RESET% !TEST_NAME!
echo %YELLOW%服务器地址：%RESET% !SERVER_URL!
echo %YELLOW%测试端点：%RESET% !ENDPOINT! (!ENDPOINT_NAME!)
echo %YELLOW%并发数：%RESET% !CONCURRENT!
echo %YELLOW%总请求数：%RESET% !TOTAL!
echo %YELLOW%超时设置：%RESET% !TIMEOUT!秒
if defined AUTH_TOKEN (
    echo %YELLOW%认证：%RESET% 已配置
) else (
    echo %YELLOW%认证：%RESET% 未配置
)
echo.

:: 高并发警告
if !CONCURRENT! gtr 200 (
    echo %RED%⚠️  警告：并发数超过 200，可能对服务器造成较大压力！%RESET%
    echo %RED%请确保：1) 在测试环境运行  2) 已通知运维人员%RESET%
    echo.
)

:: 确认开始测试
set /p "CONFIRM=是否开始测试? (y/n): "
if /i not "!CONFIRM!"=="y" (
    echo %YELLOW%测试已取消%RESET%
    pause
    exit /b 0
)

:: 创建结果目录
set "RESULT_DIR=scripts\test-results"
if not exist "!RESULT_DIR!" mkdir "!RESULT_DIR!"

:: 生成结果文件名
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set "TIMESTAMP=!datetime:~0,8!-!datetime:~8,6!"
set "RESULT_FILE=!RESULT_DIR!\stress-test-!TIMESTAMP!.txt"
set "CSV_FILE=!RESULT_DIR!\stress-test-!TIMESTAMP!.csv"

:: 开始测试
echo.
echo %CYAN%============================================================%RESET%
echo %CYAN%                    开始高并发压力测试%RESET%
echo %CYAN%============================================================%RESET%
echo.

:: 渐进式测试模式
if defined PROGRESSIVE_TEST (
    call :ProgressiveTest
    goto :TestComplete
)

:: 单次测试模式
call :SingleTest

:TestComplete
:: 记录结束时间
set "END_TIME=%TIME%"

:: 显示完成信息
echo.
echo %CYAN%============================================================%RESET%
echo %CYAN%                    测试完成%RESET%
echo %CYAN%============================================================%RESET%
echo.
echo %GREEN%测试结果文件：%RESET%
echo   - 详细报告: !RESULT_FILE!
echo   - CSV 数据: !CSV_FILE!
echo.

:: 清理临时文件
del "!RESULT_DIR!\test-script.ps1" 2>nul

:: 询问是否打开结果文件
set /p "OPEN_FILE=是否打开结果文件? (y/n): "
if /i "!OPEN_FILE!"=="y" (
    start notepad "!RESULT_FILE!"
)

:: 询问是否查看 CSV 数据
set /p "OPEN_CSV=是否查看 CSV 数据? (y/n): "
if /i "!OPEN_CSV!"=="y" (
    start excel "!CSV_FILE!" 2>nul || start notepad "!CSV_FILE!"
)

pause
exit /b 0

:: ============================================================
:: 单次测试函数
:: ============================================================
:SingleTest
echo %BLUE%正在执行 !CONCURRENT! 并发测试，请稍候...%RESET%
echo.

:: 写入结果文件头
echo ============================================================ > "!RESULT_FILE!"
echo Gipfel 高并发压力测试报告 >> "!RESULT_FILE!"
echo ============================================================ >> "!RESULT_FILE!"
echo. >> "!RESULT_FILE!"
echo 测试时间: %DATE% %TIME% >> "!RESULT_FILE!"
echo 服务器地址: !SERVER_URL! >> "!RESULT_FILE!"
echo 测试端点: !ENDPOINT! >> "!RESULT_FILE!"
echo 并发数: !CONCURRENT! >> "!RESULT_FILE!"
echo 总请求数: !TOTAL! >> "!RESULT_FILE!"
echo 超时设置: !TIMEOUT!秒 >> "!RESULT_FILE!"
echo. >> "!RESULT_FILE!"
echo ----------------------------------------------------------- >> "!RESULT_FILE!"

:: 创建 CSV 文件头
echo 请求序号,状态码,响应时间(ms),是否成功,错误信息 > "!CSV_FILE!"

:: 使用 PowerShell 进行高并发测试
powershell -ExecutionPolicy Bypass -Command "& {
    $ErrorActionPreference = 'Continue'
    
    $url = '!SERVER_URL!!ENDPOINT!'
    $concurrent = !CONCURRENT!
    $total = !TOTAL!
    $timeout = !TIMEOUT!
    $authToken = '!AUTH_TOKEN!'
    
    # 结果统计
    $results = [System.Collections.Concurrent.ConcurrentBag[PSObject]]::new()
    $successCount = 0
    $failCount = 0
    $totalTime = 0
    $minTime = [int]::MaxValue
    $maxTime = 0
    $responseTimes = [System.Collections.Concurrent.ConcurrentBag[int]]::new()
    $errors = @{}
    
    Write-Host '开始执行 $total 个请求（并发: $concurrent）...' -ForegroundColor Cyan
    Write-Host ''
    
    # 使用 .NET HttpClient 进行高并发测试
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.MaxConnectionsPerServer = $concurrent
    $handler.UseCookies = $false
    
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($timeout)
    $client.DefaultRequestHeaders.ConnectionClose = $false
    
    # 添加认证头
    if ($authToken) {
        $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $authToken)
    }
    
    # 进度显示
    $progress = 0
    $progressLock = [object]::new()
    
    # 并发执行请求
    $tasks = @()
    $startTime = [System.Diagnostics.Stopwatch]::StartNew()
    
    # 使用 SemaphoreSlim 控制并发数
    $semaphore = [System.Threading.SemaphoreSlim]::new($concurrent, $concurrent)
    
    for ($i = 1; $i -le $total; $i++) {
        $taskId = $i
        $task = [System.Threading.Tasks.Task]::Run([Action]{
            $semaphore.Wait() | Out-Null
            try {
                $sw = [System.Diagnostics.Stopwatch]::StartNew()
                
                try {
                    if ('!REQUEST_METHOD!' -eq 'POST' -and '!REQUEST_DATA!') {
                        $content = [System.Net.Http.StringContent]::new('!REQUEST_DATA!', [System.Text.Encoding]::UTF8, 'application/json')
                        $response = $client.PostAsync($url, $content).Result
                    } else {
                        $response = $client.GetAsync($url).Result
                    }
                    
                    $sw.Stop()
                    $responseTime = [int]$sw.ElapsedMilliseconds
                    
                    $result = [PSCustomObject]@{
                        Id = $taskId
                        StatusCode = [int]$response.StatusCode
                        ResponseTime = $responseTime
                        Success = $response.IsSuccessStatusCode
                        Error = ''
                    }
                    
                    $response.Dispose()
                } catch {
                    $sw.Stop()
                    $result = [PSCustomObject]@{
                        Id = $taskId
                        StatusCode = 0
                        ResponseTime = [int]$sw.ElapsedMilliseconds
                        Success = $false
                        Error = $_.Exception.Message
                    }
                }
                
                $results.Add($result)
                
                if ($result.Success) {
                    [System.Threading.Interlocked]::Increment([ref]$successCount) | Out-Null
                } else {
                    [System.Threading.Interlocked]::Increment([ref]$failCount) | Out-Null
                    if ($result.Error) {
                        $errorKey = $result.Error.Substring(0, [Math]::Min(50, $result.Error.Length))
                        if (!$errors.ContainsKey($errorKey)) {
                            $errors[$errorKey] = 0
                        }
                        $errors[$errorKey]++
                    }
                }
                
                $responseTimes.Add($result.ResponseTime)
                
                # 更新进度
                $current = [System.Threading.Interlocked]::Increment([ref]$progress)
                if ($current % 100 -eq 0) {
                    Write-Host '  已完成: $current / $total ([Math]::Round($current/$total*100, 1))%' -ForegroundColor Yellow
                }
            } finally {
                $semaphore.Release() | Out-Null
            }
        })
        $tasks += $task
    }
    
    # 等待所有任务完成
    Write-Host '等待所有请求完成...' -ForegroundColor Yellow
    [System.Threading.Tasks.Task]::WaitAll($tasks)
    $startTime.Stop()
    
    $totalSeconds = $startTime.Elapsed.TotalSeconds
    
    # 计算统计信息
    $avgTime = if ($responseTimes.Count -gt 0) { ($responseTimes | Measure-Object -Average).Average } else { 0 }
    $rps = if ($totalSeconds -gt 0) { $total / $totalSeconds } else { 0 }
    
    # 获取最小和最大响应时间
    if ($responseTimes.Count -gt 0) {
        $sortedTimes = $responseTimes | Sort-Object
        $minTime = $sortedTimes[0]
        $maxTime = $sortedTimes[-1]
        
        # 计算百分位数
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
    
    # 输出结果
    Write-Host ''
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                    测试结果' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    Write-Host '总请求数:     $total' -ForegroundColor Yellow
    Write-Host '成功请求:     $successCount' -ForegroundColor Green
    Write-Host '失败请求:     $failCount' -ForegroundColor $(if($failCount -gt 0){'Red'}else{'Green'})
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
    
    # 状态码分布
    $statusGroups = $results | Group-Object StatusCode
    Write-Host '状态码分布:' -ForegroundColor Yellow
    foreach ($group in $statusGroups) {
        $color = if ($group.Name -eq '200') { 'Green' } else { 'Red' }
        Write-Host '  $($group.Name): $($group.Count) 次' -ForegroundColor $color
    }
    Write-Host ''
    
    # 错误信息
    if ($errors.Count -gt 0) {
        Write-Host '错误信息:' -ForegroundColor Red
        foreach ($err in $errors.GetEnumerator()) {
            Write-Host '  $($err.Key): $($err.Value) 次' -ForegroundColor Red
        }
        Write-Host ''
    }
    
    # 保存详细结果到文件
    $csvContent = @()
    foreach ($result in $results) {
        $csvContent += '$($result.Id),$($result.StatusCode),$($result.ResponseTime),$($result.Success),$($result.Error)'
    }
    $csvContent | Out-File -FilePath '!CSV_FILE!' -Encoding UTF8
    
    Write-Host '详细结果已保存到: !CSV_FILE!' -ForegroundColor Green
    Write-Host ''
    
    # 性能评估
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                    性能评估' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    
    $score = 0
    $feedback = @()
    
    # RPS 评分
    if ($rps -ge 300) { $score += 30; $feedback += 'RPS 优秀 ($([Math]::Round($rps, 0)) >= 300)' }
    elseif ($rps -ge 200) { $score += 25; $feedback += 'RPS 良好 ($([Math]::Round($rps, 0)) >= 200)' }
    elseif ($rps -ge 100) { $score += 20; $feedback += 'RPS 一般 ($([Math]::Round($rps, 0)) >= 100)' }
    else { $feedback += 'RPS 需优化 ($([Math]::Round($rps, 0)) < 100)' }
    
    # 平均响应时间评分
    if ($avgTime -le 100) { $score += 30; $feedback += '响应速度 优秀 ($([Math]::Round($avgTime, 0))ms <= 100ms)' }
    elseif ($avgTime -le 300) { $score += 25; $feedback += '响应速度 良好 ($([Math]::Round($avgTime, 0))ms <= 300ms)' }
    elseif ($avgTime -le 500) { $score += 15; $feedback += '响应速度 一般 ($([Math]::Round($avgTime, 0))ms <= 500ms)' }
    else { $feedback += '响应速度 需优化 ($([Math]::Round($avgTime, 0))ms > 500ms)' }
    
    # 成功率评分
    $successRate = ($successCount / $total) * 100
    if ($successRate -ge 99) { $score += 30; $feedback += '成功率 优秀 ($([Math]::Round($successRate, 1))% >= 99%)' }
    elseif ($successRate -ge 95) { $score += 20; $feedback += '成功率 良好 ($([Math]::Round($successRate, 1))% >= 95%)' }
    elseif ($successRate -ge 90) { $score += 10; $feedback += '成功率 一般 ($([Math]::Round($successRate, 1))% >= 90%)' }
    else { $feedback += '成功率 需优化 ($([Math]::Round($successRate, 1))% < 90%)' }
    
    # P95 评分
    if ($p95 -le 500) { $score += 10; $feedback += 'P95 优秀 (${p95}ms <= 500ms)' }
    elseif ($p95 -le 1000) { $score += 5; $feedback += 'P95 良好 (${p95}ms <= 1000ms)' }
    else { $feedback += 'P95 需优化 (${p95}ms > 1000ms)' }
    
    # 输出评分
    $color = if ($score -ge 80) { 'Green' } elseif ($score -ge 60) { 'Yellow' } else { 'Red' }
    $rating = if ($score -ge 90) { 'A+ (优秀)' } elseif ($score -ge 80) { 'A (良好)' } elseif ($score -ge 70) { 'B (中等)' } elseif ($score -ge 60) { 'C (及格)' } else { 'D (需优化)' }
    
    Write-Host '综合评分: $score / 100 ($rating)' -ForegroundColor $color
    Write-Host ''
    
    Write-Host '详细评估:' -ForegroundColor Yellow
    foreach ($item in $feedback) {
        Write-Host '  • $item' -ForegroundColor $(if($item -match '优秀' -or $item -match '良好'){'Green'}elseif($item -match '一般' -or $item -match '及格' -or $item -match '中等'){'Yellow'}else{'Red'})
    }
    Write-Host ''
    
    # 高并发专项评估
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                    高并发专项评估' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    
    Write-Host '并发能力:' -ForegroundColor Yellow
    if ($rps -ge 200 -and $successRate -ge 95) {
        Write-Host '  ✓ 服务器可稳定支持 $concurrent 并发' -ForegroundColor Green
    } elseif ($rps -ge 100 -and $successRate -ge 90) {
        Write-Host '  △ 服务器可勉强支持 $concurrent 并发，建议优化' -ForegroundColor Yellow
    } else {
        Write-Host '  ✗ 服务器无法稳定支持 $concurrent 并发' -ForegroundColor Red
    }
    Write-Host ''
    
    Write-Host '响应稳定性:' -ForegroundColor Yellow
    $timeRange = $maxTime - $minTime
    if ($timeRange -lt 500) {
        Write-Host '  ✓ 响应时间稳定，波动小于 500ms' -ForegroundColor Green
    } elseif ($timeRange -lt 1000) {
        Write-Host '  △ 响应时间有波动，范围 $([Math]::Round($timeRange, 0))ms' -ForegroundColor Yellow
    } else {
        Write-Host '  ✗ 响应时间波动大，范围 $([Math]::Round($timeRange, 0))ms' -ForegroundColor Red
    }
    Write-Host ''
    
    # 优化建议
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host '                    优化建议' -ForegroundColor Cyan
    Write-Host '============================================================' -ForegroundColor Cyan
    Write-Host ''
    
    if ($rps -lt 200) {
        Write-Host 'RPS 较低，建议:' -ForegroundColor Yellow
        Write-Host '  1. 增加 Daphne worker 数量（当前建议 4-6 个）' -ForegroundColor White
        Write-Host '  2. 启用 Nginx 缓冲和压缩' -ForegroundColor White
        Write-Host '  3. 使用数据库连接池' -ForegroundColor White
        Write-Host '  4. 考虑迁移到 PostgreSQL' -ForegroundColor White
    }
    
    if ($avgTime -gt 300) {
        Write-Host '响应时间较长，建议:' -ForegroundColor Yellow
        Write-Host '  1. 检查数据库查询是否优化' -ForegroundColor White
        Write-Host '  2. 添加 Redis 缓存' -ForegroundColor White
        Write-Host '  3. 优化 Nginx 代理配置' -ForegroundColor White
        Write-Host '  4. 检查是否有慢查询' -ForegroundColor White
    }
    
    if ($failCount -gt 0) {
        Write-Host '存在失败请求，建议:' -ForegroundColor Yellow
        Write-Host '  1. 检查服务器日志' -ForegroundColor White
        Write-Host '  2. 增加服务器资源' -ForegroundColor White
        Write-Host '  3. 检查数据库连接数限制' -ForegroundColor White
        Write-Host '  4. 检查 Nginx 连接数限制' -ForegroundColor White
    }
    
    if ($score -ge 80) {
        Write-Host '服务器性能良好！' -ForegroundColor Green
        Write-Host '  继续保持当前配置。' -ForegroundColor White
    }
    Write-Host ''
    
    # 保存结果摘要
    $summary = @'
============================================================
测试结果摘要
============================================================
测试时间: $(Get-Date)
服务器: !SERVER_URL!
端点: !ENDPOINT!
并发数: !CONCURRENT!
总请求数: !TOTAL!

成功: $successCount
失败: $failCount
成功率: $([Math]::Round($successRate, 2))%

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
    
    $summary | Out-File -FilePath '!RESULT_FILE!' -Encoding UTF8
    
    Write-Host '测试报告已保存到: !RESULT_FILE!' -ForegroundColor Green
    Write-Host ''
    
    # 返回测试结果
    return @{
        SuccessCount = $successCount
        FailCount = $failCount
        TotalSeconds = $totalSeconds
        RPS = $rps
        AvgTime = $avgTime
        MinTime = $minTime
        MaxTime = $maxTime
        P50 = $p50
        P95 = $p95
        P99 = $p99
        Score = $score
        SuccessRate = $successRate
    }
}"

echo.
goto :eof

:: ============================================================
:: 渐进式测试函数
:: ============================================================
:ProgressiveTest
echo %BLUE%开始渐进式测试，逐步增加并发数...%RESET%
echo.

:: 写入结果文件头
echo ============================================================ > "!RESULT_FILE!"
echo Gipfel 渐进式压力测试报告 >> "!RESULT_FILE!"
echo ============================================================ >> "!RESULT_FILE!"
echo. >> "!RESULT_FILE!"
echo 测试时间: %DATE% %TIME% >> "!RESULT_FILE!"
echo 服务器地址: !SERVER_URL! >> "!RESULT_FILE!"
echo 测试端点: !ENDPOINT! >> "!RESULT_FILE!"
echo. >> "!RESULT_FILE!"
echo ----------------------------------------------------------- >> "!RESULT_FILE!"

:: 创建 CSV 文件头
echo 并发数,总请求数,成功数,失败数,成功率,RPS,平均响应时间,P50,P95,P99,评分 > "!CSV_FILE!"

:: 渐进式测试
for %%c in (50 100 150 200 250 300) do (
    set "CONCURRENT=%%c"
    set /a "TOTAL=%%c * 10"
    
    echo.
    echo %CYAN%------------------------------------------------------------%RESET%
    echo %CYAN%测试阶段: %%c 并发, !TOTAL! 请求%RESET%
    echo %CYAN%------------------------------------------------------------%RESET%
    
    :: 执行测试并获取结果
    powershell -ExecutionPolicy Bypass -Command "& {
        $ErrorActionPreference = 'Continue'
        
        $url = '!SERVER_URL!!ENDPOINT!'
        $concurrent = %%c
        $total = !TOTAL!
        $timeout = 30
        $authToken = '!AUTH_TOKEN!'
        
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
        $client.Timeout = [TimeSpan]::FromSeconds($timeout)
        $client.DefaultRequestHeaders.ConnectionClose = $false
        
        if ($authToken) {
            $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $authToken)
        }
        
        $semaphore = [System.Threading.SemaphoreSlim]::new($concurrent, $concurrent)
        $progress = 0
        
        $tasks = @()
        $startTime = [System.Diagnostics.Stopwatch]::StartNew()
        
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
        Write-Host '  成功: $successCount / $total ($successRate%)' -ForegroundColor $(if($successRate -ge 95){'Green'}else{'Red'})
        Write-Host '  RPS: $([Math]::Round($rps, 2))' -ForegroundColor $(if($rps -ge 200){'Green'}else{'Yellow'})
        Write-Host '  平均响应: $([Math]::Round($avgTime, 2))ms' -ForegroundColor $(if($avgTime -le 300){'Green'}else{'Red'})
        Write-Host '  P95: ${p95}ms' -ForegroundColor $(if($p95 -le 500){'Green'}else{'Red'})
        Write-Host '  评分: $score / 100' -ForegroundColor $(if($score -ge 70){'Green'}elseif($score -ge 50){'Yellow'}else{'Red'})
        
        # 返回结果
        return @{
            Concurrent = $concurrent
            Total = $total
            SuccessCount = $successCount
            FailCount = $failCount
            SuccessRate = $successRate
            RPS = $rps
            AvgTime = $avgTime
            P50 = $p50
            P95 = $p95
            P99 = $p99
            Score = $score
        }
    }"
    
    echo.
    timeout /t 2 /nobreak >nul
)

echo.
echo %CYAN%============================================================%RESET%
echo %CYAN%                    渐进式测试完成%RESET%
echo %CYAN%============================================================%RESET%
echo.
echo %GREEN%请查看 CSV 文件了解完整结果：%RESET%
echo   !CSV_FILE!
echo.
echo %YELLOW%建议：%RESET%
echo   1. 在 Excel 中打开 CSV 文件
echo   2. 绘制并发数 vs RPS 图表
echo   3. 绘制并发数 vs 响应时间图表
echo   4. 找到性能拐点（RPS 开始下降或响应时间急剧上升的点）
echo   5. 将该并发数作为服务器的稳定并发上限
echo.

goto :eof