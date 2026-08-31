@echo off
REM ========================================================================
REM  Gipfel - PRODUCTION - deploy to local folder - bat launcher
REM  RUN AS ADMINISTRATOR (net session is used to assert admin rights).
REM
REM  Defaults:
REM      install dir     : C:\gipfel
REM      backend port    : 8000
REM      frontend port   : 80
REM      register service: 0 (= disabled; pass 1 to enable nssm service)
REM
REM  Example (in an admin CMD):
REM      cd /d %~dp0
REM      deploy-windows.bat  C:\gipfel  8000  80  1
REM
REM  Errors are shown directly in this window. The script pauses on failure
REM  so you can read the message; nothing is written to a log file.
REM ========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

REM --- Admin check (must run elevated) ---
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] This script requires ADMINISTRATOR rights.
    echo         Action: Start CMD -^> Right-click -^> Run as administrator
    echo         Then re-run: deploy-windows.bat
    echo.
    pause
    exit /b 1
)

set "PS1=%~dpn0.ps1"

set "ARG1=%~1"
if "%ARG1%"=="" set "ARG1=C:\gipfel"
set "ARG2=%~2"
if "%ARG2%"=="" set "ARG2=8000"
set "ARG3=%~3"
if "%ARG3%"=="" set "ARG3=80"
set "ARG4=%~4"
if "%ARG4%"=="" set "ARG4=0"

echo ------------------------------------------------------------
echo  Gipfel - PRODUCTION - Deploy to Windows
echo  Install dir   : %ARG1%
echo  Backend port  : %ARG2%
echo  Frontend port : %ARG3%
echo  Register svc  : %ARG4%  (1 = enable GipfelBackend via nssm)
echo  PowerShell script : %PS1%
echo ------------------------------------------------------------
echo.

if not exist "%PS1%" (
    echo [ERROR] Missing file: %PS1%
    pause
    exit /b 1
)

REM Run the deployment. Output goes straight to this window (no log file).
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" ^
    -InstallDir "%ARG1%" -Port "%ARG2%" -FrontendPort "%ARG3%" ^
    -WithService:("%ARG4%"=="1") -ForceOverwrite
set "EC=%ERRORLEVEL%"

echo.
if "%EC%"=="0" (
    echo ------------------------------------------------------------
    echo   Deploy succeeded.
    echo ------------------------------------------------------------
) else (
    echo ------------------------------------------------------------
    echo   Deploy FAILED. exitcode=%EC%
    echo   The error above is shown in this window.
    echo ------------------------------------------------------------
)
echo.
echo Press any key to close this window...
pause >nul
exit /b %EC%
