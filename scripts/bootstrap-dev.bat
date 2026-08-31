@echo off
REM ========================================================================
REM  Gipfel - DEVELOPMENT - Bootstrap - bat launcher
REM  Double-click this file to set up the dev environment once.
REM  Thin wrapper that always pauses on failure so the window never flashes
REM  away; real work is delegated to bootstrap-dev.ps1.
REM
REM  Errors are shown directly in this window. The script pauses on failure
REM  so you can read the message; nothing is written to a log file.
REM ========================================================================
setlocal
chcp 65001 >nul

REM Normalize working dir to where this .bat lives (scripts folder)
cd /d "%~dp0"
set "PS1=%~dpn0.ps1"

echo ------------------------------------------------------------
echo  Gipfel - DEVELOPMENT - Bootstrap
echo  PowerShell script : %PS1%
echo ------------------------------------------------------------
echo.

if not exist "%PS1%" (
    echo [ERROR] Missing file: %PS1%
    echo.
    pause
    exit /b 1
)

REM Run bootstrap. Output goes straight to this window (no log file).
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "EC=%ERRORLEVEL%"

echo.
if "%EC%"=="0" (
    echo ------------------------------------------------------------
    echo   Bootstrap OK. Next step: double-click start-dev.bat
    echo ------------------------------------------------------------
) else (
    echo ------------------------------------------------------------
    echo   Bootstrap FAILED. exitcode=%EC%
    echo   The error above is shown in this window.
    echo ------------------------------------------------------------
)
echo.
echo Press any key to close this window...
pause >nul
exit /b %EC%
