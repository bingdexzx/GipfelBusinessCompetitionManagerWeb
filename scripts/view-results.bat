@echo off
REM ========================================================================
REM  Gipfel test result viewer launcher
REM  IMPORTANT: keep this file ASCII-only and CRLF-terminated.
REM  Non-ASCII bytes or LF-only line endings make cmd.exe mis-parse the file.
REM  All real logic (and all Chinese text) lives in view-results.ps1.
REM ========================================================================
setlocal
where powershell >nul 2>nul
if errorlevel 1 (
  echo [ERROR] powershell.exe not found in PATH.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0view-results.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] script exited with code %RC%
  pause
)
exit /b %RC%
