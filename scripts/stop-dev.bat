@echo off
REM ========================================================================
REM  Gipfel - DEVELOPMENT - Force stop Django (8000) + Vite (5173) +
REM  LogViewer (8120). Use this when the "Gipfel Dev" window was closed with
REM  the X button (or killed in Task Manager) and the servers are still alive.
REM  Pure ASCII file (English comments only).
REM
REM  1) kill every pid recorded by scripts\dev.py in %TEMP%\gipfel-dev.pids
REM  2) fallback: kill whoever still listens on the dev ports
REM ========================================================================
setlocal
chcp 65001 >nul
set "PIDFILE=%TEMP%\gipfel-dev.pids"
set "KILLED=0"

if exist "%PIDFILE%" (
  for /f "usebackq tokens=*" %%p in ("%PIDFILE%") do (
    taskkill /PID %%p /T /F >nul 2>nul
    if not errorlevel 1 set "KILLED=1"
  )
  del /q "%PIDFILE%" >nul 2>nul
)

for %%P in (8000 5173 8120) do (
  for /f "tokens=5" %%a in ('netstat -ano ^| findstr /r ":%%P .*LISTENING"') do (
    taskkill /PID %%a /T /F >nul 2>nul
    if not errorlevel 1 set "KILLED=1"
  )
)

if "%KILLED%"=="1" (
  echo [OK]    Dev services stopped.
) else (
  echo [INFO]  No dev service was running.
)
exit /b 0
