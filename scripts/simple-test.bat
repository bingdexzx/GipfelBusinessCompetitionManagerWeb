@echo off
chcp 65001 >nul

echo.
echo ============================================================
echo        Gipfel 简单压力测试
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
echo 测试目标: %SERVER%/api/health
echo.

:: 检查 curl 是否可用
where curl >nul 2>nul
if %errorlevel% neq 0 (
    echo [警告] 未找到 curl 命令，将使用 PowerShell 进行测试。
    echo.
    goto :use_powershell
)

echo 正在使用 curl 测试...
echo.

:: 发送 10 个请求测试
for /L %%i in (1,1,10) do (
    echo 请求 %%i:
    curl -s -o nul -w "  状态码: %%{http_code}  响应时间: %%{time_total}s\n" "%SERVER%/api/health" 2>nul
    if errorlevel 1 (
        echo   连接失败！
    )
)

goto :done

:use_powershell
echo 正在使用 PowerShell 测试...
echo.

set "PS_FILE=%temp%\gipfel-simple-test.ps1"
call :write_ps1 > "%PS_FILE%"
powershell -ExecutionPolicy Bypass -File "%PS_FILE%"
del "%PS_FILE%" 2>nul

goto :done

:done
echo.
echo 测试完成！
echo.
pause
exit /b 0

:: PowerShell 后备测试脚本
:write_ps1
echo $url = '%SERVER%/api/health'
echo for ($i = 1; $i -le 10; $i++) {
echo     Write-Host ("请求 {0}:" -f $i) -NoNewline
echo     try {
echo         $sw = [System.Diagnostics.Stopwatch]::StartNew()
echo         $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
echo         $sw.Stop()
echo         Write-Host ("  状态码: {0}  响应时间: {1}ms" -f $r.StatusCode, $sw.ElapsedMilliseconds)
echo     } catch {
echo         Write-Host "  连接失败！" -ForegroundColor Red
echo     }
echo }
goto :eof
