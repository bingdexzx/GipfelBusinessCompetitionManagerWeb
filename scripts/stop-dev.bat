@echo off
REM ========================================================================
REM  Gipfel - DEVELOPMENT - Stop Django (8000) + Vite (5173) + LogViewer (8120).
REM  Use this when the "Gipfel Dev" window was closed with the X button (or
REM  killed in Task Manager) and the servers are still alive.
REM  Pure ASCII file (English comments only).
REM
REM  This is a THIN WRAPPER around `python scripts\dev.py stop`, which only
REM  stops processes whose identity (image name + creation time + project id)
REM  still matches what dev.py recorded, and never kills by port number.
REM
REM  History: an earlier version ran `taskkill /PID <every pid in the pidfile>`
REM  and `taskkill /PID <whoever listens on 8000/5173/8120>`. That could kill
REM  unrelated services (Docker Desktop, another Vite, your own servers) and
REM  could kill a recycled PID recorded hours ago. Both paths are gone.
REM ========================================================================
setlocal
chcp 65001 >nul

set "PYEXE=%~dp0..\backend\.venv\Scripts\python.exe"
if not exist "%PYEXE%" (
  echo [ERR]   %PYEXE% not found. Run scripts\bootstrap-dev.bat first.
  exit /b 1
)

"%PYEXE%" "%~dp0dev.py" stop
exit /b %ERRORLEVEL%
