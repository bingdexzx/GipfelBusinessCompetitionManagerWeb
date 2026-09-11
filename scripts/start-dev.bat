@echo off
REM ========================================================================
REM  Gipfel - DEVELOPMENT - Start Django (8000) + Vite (5173) + LogViewer (8120)
REM  Pure ASCII file (English comments only).
REM
REM  This batch only checks the preconditions and then hands over to
REM  scripts\dev.py in a window of its own ("Gipfel Dev").
REM
REM  Why not start the servers right here with `start /B`?
REM    - cmd's `start` puts every child process into a NEW process group, and
REM      the console CTRL+C is NOT delivered to it: the three servers keep
REM      running (ports 8000/5173/8120 stay occupied);
REM    - cmd.exe itself stops at "Terminate batch job (Y/N)?" while the
REM      streamed server output keeps scrolling - the window looks frozen.
REM  dev.py is the supervisor: one Ctrl+C stops all three services cleanly
REM  (targeted CTRL_BREAK per process group, taskkill /T /F as fallback).
REM
REM  If a window was closed with the X button and services are still alive:
REM    scripts\stop-dev.bat
REM ========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "BACKEND=%~dp0..\backend"
set "FRONTEND=%~dp0..\frontend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo [ERROR] %PY% not found. Run scripts\bootstrap-dev.bat first.
  goto :fail
)
if not exist "%~dp0dev.py" (
  echo [ERROR] %~dp0dev.py not found.
  goto :fail
)
if not exist "%FRONTEND%\node_modules\.bin\vite.cmd" (
  echo [ERROR] Frontend deps missing. Run scripts\bootstrap-dev.bat first.
  goto :fail
)

echo [INFO]  Starting Gipfel dev services in a new window ("Gipfel Dev") ...
start "Gipfel Dev" "%PY%" "%~dp0dev.py"
exit /b 0

:fail
echo.
echo [ERROR] start-dev FAILED. See messages above.
echo.
pause
exit /b 1
