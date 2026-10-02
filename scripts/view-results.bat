@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================================
:: Gipfel 测试结果查看工具
:: 用于查看和分析压力测试结果
:: ============================================================

title Gipfel 测试结果查看工具

echo.
echo [96m============================================================[0m
echo [96m       Gipfel 测试结果查看工具[0m
echo [96m============================================================[0m
echo.

:: 检查结果目录
set "RESULT_DIR=scripts\test-results"
if not exist "!RESULT_DIR!" (
    echo [91m错误：未找到测试结果目录[0m
    echo [91m请先运行压力测试: scripts\stress-test.bat[0m
    pause
    exit /b 1
)

:: 列出所有测试结果
echo [94m可用的测试结果：[0m
echo.

set "COUNT=0"
for %%f in ("!RESULT_DIR!\stress-test-*.txt") do (
    set /a "COUNT+=1"
    set "FILE_!COUNT!=%%f"
    echo [92m!COUNT!. %%~nxf[0m
)

for %%f in ("!RESULT_DIR!\quick-test-*.txt") do (
    set /a "COUNT+=1"
    set "FILE_!COUNT!=%%f"
    echo [92m!COUNT!. %%~nxf[0m
)

if !COUNT! equ 0 (
    echo [91m未找到测试结果文件[0m
    pause
    exit /b 1
)

echo.
set /p "CHOICE=请选择要查看的结果 (1-!COUNT!): "

if !CHOICE! lss 1 (
    echo [91m无效选择[0m
    pause
    exit /b 1
)

if !CHOICE! gtr !COUNT! (
    echo [91m无效选择[0m
    pause
    exit /b 1
)

:: 获取选中的文件
set "SELECTED_FILE=!FILE_%CHOICE%!"
set "CSV_FILE=!SELECTED_FILE:.txt=.csv!"

echo.
echo [96m============================================================[0m
echo [96m                    测试结果详情[0m
echo [96m============================================================[0m
echo.

:: 显示测试报告
echo [94m测试报告：[0m
echo.
type "!SELECTED_FILE!"
echo.

:: 检查是否有 CSV 文件
if exist "!CSV_FILE!" (
    echo [96m============================================================[0m
    echo [96m                    数据分析[0m
    echo [96m============================================================[0m
    echo.
    
    :: 使用子程序生成分析脚本并执行
    set "PS_FILE=%temp%\gipfel-analysis.ps1"
    call :write_analysis > "!PS_FILE!"
    powershell -ExecutionPolicy Bypass -File "!PS_FILE!"
    del "!PS_FILE!" 2>nul
    
    echo.
    echo [94m是否打开 CSV 文件进行详细分析?[0m
    set /p "OPEN_CSV=输入 y 打开 Excel，输入 n 跳过: "
    if /i "!OPEN_CSV!"=="y" (
        start excel "!CSV_FILE!" 2>nul || start notepad "!CSV_FILE!"
    )
)

echo.
echo [96m============================================================[0m
echo [96m                    操作选项[0m
echo [96m============================================================[0m
echo.
echo [92m1. 打开测试报告[0m
echo [92m2. 打开 CSV 数据[0m
echo [92m3. 导出为 HTML 报告[0m
echo [92m4. 返回[0m
echo.

set /p "ACTION=请选择操作 (1-4): "

if "!ACTION!"=="1" (
    start notepad "!SELECTED_FILE!"
) else if "!ACTION!"=="2" (
    if exist "!CSV_FILE!" (
        start excel "!CSV_FILE!" 2>nul || start notepad "!CSV_FILE!"
    ) else (
        echo [91mCSV 文件不存在[0m
    )
) else if "!ACTION!"=="3" (
    :: 生成 HTML 报告
    set "HTML_FILE=!SELECTED_FILE:.txt=.html!"
    
    echo [94m正在生成 HTML 报告...[0m
    
    (
echo ^<!DOCTYPE html^>
echo ^<html lang="zh-CN"^>
echo ^<head^>
echo     ^<meta charset="UTF-8"^>
echo     ^<title^>Gipfel 压力测试报告^</title^>
echo     ^<style^>
echo         body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
echo         .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
echo         h1 { color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }
echo         h2 { color: #555; margin-top: 30px; }
echo         .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 20px 0; }
echo         .card { background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; }
echo         .card h3 { margin: 0 0 10px 0; color: #666; font-size: 14px; }
echo         .card .value { font-size: 32px; font-weight: bold; color: #007bff; }
echo         .success { color: #28a745; }
echo         .warning { color: #ffc107; }
echo         .danger { color: #dc3545; }
echo         table { width: 100%%; border-collapse: collapse; margin: 20px 0; }
echo         th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
echo         th { background: #007bff; color: white; }
echo         tr:hover { background: #f5f5f5; }
echo         .chart { margin: 20px 0; padding: 20px; background: #f8f9fa; border-radius: 8px; }
echo         .bar { height: 30px; background: #007bff; margin: 5px 0; border-radius: 4px; display: flex; align-items: center; padding-left: 10px; color: white; font-size: 12px; }
echo     ^</style^>
echo ^</head^>
echo ^<body^>
echo     ^<div class="container"^>
echo         ^<h1^>Gipfel 压力测试报告^</h1^>
echo         ^<p^>生成时间: %DATE% %TIME%^</p^>
echo         ^<pre^> > "!HTML_FILE!"
    
    type "!SELECTED_FILE!" >> "!HTML_FILE!"
    
    (
echo         ^</pre^>
echo     ^</div^>
echo ^</body^>
echo ^</html^>
    ) >> "!HTML_FILE!"
    
    echo [92mHTML 报告已生成: !HTML_FILE![0m
    start "!HTML_FILE!"
) else if "!ACTION!"=="4" (
    exit /b 0
)

echo.
pause
exit /b 0

:: ============================================================
:: 子程序：生成 PowerShell CSV 分析脚本
:: ============================================================
:write_analysis
echo $csvFile = '!CSV_FILE!'
echo $data = Import-Csv -Path $csvFile
echo.
echo # 基本统计
echo $total = $data.Count
echo $success = ($data ^| Where-Object { $_.'成功' -eq 'True' }).Count
echo $fail = $total - $success
echo.
echo # 响应时间统计
echo $times = $data ^| ForEach-Object { [int]$_.'响应时间' }
echo $avg = ($times ^| Measure-Object -Average).Average
echo $min = ($times ^| Measure-Object -Minimum).Minimum
echo $max = ($times ^| Measure-Object -Maximum).Maximum
echo.
echo # 百分位数
echo $sorted = $times ^| Sort-Object
echo $p50 = $sorted[[math]::Floor($total * 0.5)]
echo $p95 = $sorted[[math]::Floor($total * 0.95)]
echo $p99 = $sorted[[math]::Floor($total * 0.99)]
echo.
echo # 状态码分布
echo $statusGroups = $data ^| Group-Object '状态码'
echo.
echo Write-Host ''
echo Write-Host '数据统计:' -ForegroundColor Yellow
echo Write-Host "  总请求数:     $total"
echo Write-Host "  成功请求:     $success"
echo Write-Host "  失败请求:     $fail"
echo Write-Host ''
echo.
echo Write-Host '响应时间分布:' -ForegroundColor Yellow
echo Write-Host "  最小值:       $min ms"
echo Write-Host "  最大值:       $max ms"
echo Write-Host "  平均值:       $([math]::Round($avg, 2)) ms"
echo Write-Host "  P50:          $p50 ms"
echo Write-Host "  P95:          $p95 ms"
echo Write-Host "  P99:          $p99 ms"
echo Write-Host ''
echo.
echo Write-Host '状态码分布:' -ForegroundColor Yellow
echo foreach ($group in $statusGroups) {
echo     $color = if ($group.Name -eq '200') { 'Green' } else { 'Red' }
echo     Write-Host ("  {0}: {1} 次" -f $group.Name, $group.Count) -ForegroundColor $color
echo }
echo Write-Host ''
echo.
echo # 响应时间分布图
echo Write-Host '响应时间分布:' -ForegroundColor Yellow
echo $buckets = @{
echo     '0-100ms' = 0
echo     '100-200ms' = 0
echo     '200-500ms' = 0
echo     '500-1000ms' = 0
echo     '1000-2000ms' = 0
echo     '^>2000ms' = 0
echo }
echo.
echo foreach ($t in $times) {
echo     if ($t -lt 100) { $buckets['0-100ms']++ }
echo     elseif ($t -lt 200) { $buckets['100-200ms']++ }
echo     elseif ($t -lt 500) { $buckets['200-500ms']++ }
echo     elseif ($t -lt 1000) { $buckets['500-1000ms']++ }
echo     elseif ($t -lt 2000) { $buckets['1000-2000ms']++ }
echo     else { $buckets['^>2000ms']++ }
echo }
echo.
echo foreach ($bucket in $buckets.GetEnumerator() ^| Sort-Object Name) {
echo     $bar = [string][char]0x2588 * [math]::Min([math]::Floor($bucket.Value / $total * 50), 50)
echo     $pct = [math]::Round($bucket.Value / $total * 100, 1)
echo     Write-Host ('  {0,-15} {1,5} ({2,5}%%) {3}' -f $bucket.Key, $bucket.Value, $pct, $bar)
echo }
echo Write-Host ''
goto :eof
