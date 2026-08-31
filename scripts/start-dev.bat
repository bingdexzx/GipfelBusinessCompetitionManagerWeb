@echo off
REM ========================================================================
REM  Gipfel - DEVELOPMENT - Start Django (:8000) + Vite (:5173) - bat launcher
REM  Double-click to run; real logic in start-dev.ps1 (bat wrapper ensures:
REM  the console window stays open on failure with "press any key" pause).
REM  Ctrl+C / closing the console triggers cleanup that kills both subprocs.
REM
REM  Errors are shown directly in this window. The script pauses on failure
REM  so you can read the message; nothing is written to a log file.
REM ========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PS1=%~dpn0.ps1"

echo ------------------------------------------------------------
echo  Gipfel - DEVELOPMENT - Start Django + Vite
echo  PowerShell script : %PS1%
echo ------------------------------------------------------------
echo.

if not exist "%PS1%" (
    echo [ERROR] Missing file: %PS1%
    pause
    exit /b 1
)

REM Run the dev servers. Output goes straight to this window (no log file).
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "EC=%ERRORLEVEL%"

echo.
if NOT "%EC%"=="0" (
    echo ------------------------------------------------------------
    echo   start-dev FAILED. exitcode=%EC%
    echo   The error above is shown in this window.
    echo ------------------------------------------------------------
    echo.
    echo Press any key to close this window...
    pause >nul
)
exit /b %EC%
