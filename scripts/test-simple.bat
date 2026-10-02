@echo off
chcp 65001 >nul
setlocal

echo.
echo ============================================================
echo        Gipfel 快速连通性测试
echo ============================================================
echo.

:: 获取服务器地址
set /p "SERVER=请输入服务器地址 (例如: http://your-domain.com): "
if "%SERVER%"=="" (
    echo 错误：服务器不能为空！
    pause
    exit /b 1
)

:: 移除末尾斜杠
if "%SERVER:~-1%"=="/" set "SERVER=%SERVER:~0,-1%"

echo.
echo 正在测试 %SERVER% ...
echo.

:: 生成并执行 PowerShell 测试脚本
set "PS_FILE=%temp%\gipfel-conn-test.ps1"
call :write_ps1 > "%PS_FILE%"
powershell -ExecutionPolicy Bypass -File "%PS_FILE%"
del "%PS_FILE%" 2>nul

echo.
pause
exit /b 0

:: 连通性测试脚本
:write_ps1
echo $url = '%SERVER%'
echo $tests = @(
echo     @{ Name = '健康检查'; Path = '/api/health' }
echo     @{ Name = '版本信息'; Path = '/api/version' }
echo     @{ Name = '首页访问'; Path = '/' }
echo )
echo Write-Host '测试结果:' -ForegroundColor Cyan
echo Write-Host ''
echo foreach ($test in $tests) {
echo     Write-Host ("  {0} ({1})... " -f $test.Name, $test.Path) -NoNewline
echo     try {
echo         $sw = [System.Diagnostics.Stopwatch]::StartNew()
echo         $r = Invoke-WebRequest -Uri "$url$($test.Path)" -UseBasicParsing -TimeoutSec 10
echo         $sw.Stop()
echo         Write-Host ("OK {0} ({1}ms)" -f $r.StatusCode, $sw.ElapsedMilliseconds) -ForegroundColor Green
echo     } catch {
echo         $msg = $_.Exception.Message
echo         if ($msg -match '404') {
echo             Write-Host "404 (端点不存在)" -ForegroundColor Yellow
echo         } else {
echo             Write-Host ("FAIL: {0}" -f $msg) -ForegroundColor Red
echo         }
echo     }
echo }
echo Write-Host ''
echo Write-Host '连通性测试完成！' -ForegroundColor Cyan
goto :eof
