@echo off
REM ========================================================================
REM  Gipfel - DEVELOPMENT - Start Django (8000) + Vite (5173) + LogViewer (8120)
REM  Self-contained batch, no PowerShell. Double-click to run.
REM  Pure ASCII file (English comments only).
REM
REM  - Starts three background servers; their stdout/stderr stream here.
REM  - LogViewer port comes from backend\.env LOG_VIEWER_PORT (default 8120).
REM  - Press Ctrl+C to stop all child processes (they share this console).
REM  - Pre-run health probes print the three URLs when ready.
REM ========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "BACKEND=%~dp0..\backend"
set "FRONTEND=%~dp0..\frontend"
set "LOGVIEWER=%BACKEND%\logviewer"
set "BACKEND_BIND=127.0.0.1:8000"
set "VITE_PORT=5173"
set "LOGVIEWER_HOST=127.0.0.1"
set "LOGVIEWER_PORT=8120"

REM read LOG_VIEWER_PORT from backend/.env
if exist "%BACKEND%\.env" (
  for /f "tokens=1,* delims==" %%a in ('findstr /b "LOG_VIEWER_PORT=" "%BACKEND%\.env"') do set "LOGVIEWER_PORT=%%b"
)
echo %LOGVIEWER_PORT% | findstr /r "^[0-9][0-9]*$" >nul || set "LOGVIEWER_PORT=8120"

REM ---------- preconditions ----------
set "PY=%BACKEND%\.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] %PY% not found. Run scripts\bootstrap-dev.bat first.
  goto :fail
)
if not exist "%FRONTEND%\node_modules\.bin\vite.cmd" (
  echo [ERROR] Frontend deps missing. Run scripts\bootstrap-dev.bat first.
  goto :fail
)

REM ---------- 1) Django ----------
echo [INFO]  Starting Django -^> %BACKEND_BIND%
cd /d "%BACKEND%"
start "Gipfel-Django" /B "%PY%" manage.py runserver %BACKEND_BIND% --noreload
timeout /T 1 /NOBREAK >nul

echo [INFO]  Probing Django http://%BACKEND_BIND%/api/health ...
set "DJOK=0"
for /L %%i in (1,1,24) do (
  curl -sf -m 2 "http://%BACKEND_BIND%/api/health" -o nul
  if not errorlevel 1 (
    echo [OK]    Django ready
    set "DJOK=1"
    goto :django_ok
  )
  timeout /T 1 /NOBREAK >nul
)
:django_ok
if "%DJOK%"=="0" echo [WARN]  Django not responding after 24s (continuing anyway)

REM ---------- 2) Vite ----------
echo [INFO]  Starting Vite -^> 127.0.0.1:%VITE_PORT%
cd /d "%FRONTEND%"
start "Gipfel-Vite" /B npm run dev -- --host 127.0.0.1 --port %VITE_PORT%
timeout /T 1 /NOBREAK >nul

echo [INFO]  Probing Vite http://127.0.0.1:%VITE_PORT%/ ...
set "VOK=0"
for /L %%i in (1,1,30) do (
  curl -sf -m 2 "http://127.0.0.1:%VITE_PORT%/" -o nul
  if not errorlevel 1 (
    echo [OK]    Vite ready
    set "VOK=1"
    goto :vite_ok
  )
  timeout /T 1 /NOBREAK >nul
)
:vite_ok
if "%VOK%"=="0" echo [WARN]  Vite not responding after 30s (continuing anyway)

REM ---------- 3) LogViewer ----------
if not exist "%LOGVIEWER%\manage.py" (
  echo [WARN]  %LOGVIEWER%\manage.py not found, skip LogViewer
  goto :lv_skip
)
echo [INFO]  Starting LogViewer -^> %LOGVIEWER_HOST%:%LOGVIEWER_PORT%
cd /d "%LOGVIEWER%"
start "Gipfel-LogViewer" /B "%PY%" manage.py runserver %LOGVIEWER_HOST%:%LOGVIEWER_PORT% --noreload
timeout /T 1 /NOBREAK >nul

echo [INFO]  Probing LogViewer http://%LOGVIEWER_HOST%:%LOGVIEWER_PORT%/api/health ...
set "LVOK=0"
for /L %%i in (1,1,24) do (
  curl -sf -m 2 "http://%LOGVIEWER_HOST%:%LOGVIEWER_PORT%/api/health" -o nul
  if not errorlevel 1 (
    echo [OK]    LogViewer ready
    set "LVOK=1"
    goto :lv_ok
  )
  timeout /T 1 /NOBREAK >nul
)
:lv_ok
if "%LVOK%"=="0" echo [WARN]  LogViewer not responding after 24s (continuing anyway)
:lv_skip

REM ---------- summary + keepalive ----------
echo.
echo [OK]    All services started.
echo    Frontend (Vite) : http://127.0.0.1:%VITE_PORT%
echo    Backend  (Django): http://%BACKEND_BIND%
echo    LogViewer        : http://%LOGVIEWER_HOST%:%LOGVIEWER_PORT%  (account = Django superadmin)
echo    Server output streams to this window (no log file).
echo.
echo [WARN]  Press Ctrl+C to stop all child processes.
:keepalive
timeout /T 2 /NOBREAK >nul
goto :keepalive

:fail
echo.
echo [ERROR] start-dev FAILED. See messages above.
echo.
cd /d "%~dp0"
exit /b 1
