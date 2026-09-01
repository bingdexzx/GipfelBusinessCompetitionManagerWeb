@echo off
REM ========================================================================
REM  Gipfel - DEVELOPMENT - Bootstrap (self-contained batch, no PowerShell)
REM  Double-click to set up the dev environment once.
REM  Pure ASCII file (English comments only).
REM
REM  What it does:
REM    1. Check Python (>=3.10) and Node/npm
REM    2. Copy backend\.env.example -> backend\.env (if missing)
REM    3. Create backend\.venv + pip install -r requirements.txt
REM    4. python manage.py check + migrate  (first migrate seeds admin/admin123)
REM    5. npm install in frontend
REM
REM  Optional: pass --skip-frontend to skip Node/npm steps.
REM ========================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "BACKEND=%~dp0..\backend"
set "FRONTEND=%~dp0..\frontend"
set "SKIPFE=0"
if /i "%~1"=="--skip-frontend" set "SKIPFE=1"

REM ---------- 1. Environment checks ----------
echo [INFO]  Checking environment...
REM 探测可用的 Python 命令：优先 python，其次 py -3，最后退而用已存在的 .venv
set "PYCMD="
where python >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if not defined PYCMD (
  py -3 --version >nul 2>nul
  if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
  if exist "%BACKEND%\.venv\Scripts\python.exe" set "PYCMD=%BACKEND%\.venv\Scripts\python.exe"
)
if not defined PYCMD (
  echo [ERROR] Python 3.10+ not found. Install Python 3.10+ (add to PATH) or the Windows Store 'py' launcher.
  goto :fail
)
for /f "tokens=*" %%v in ('%PYCMD% -c "import sys;print(sys.version_info.major)"') do set "PYMAJOR=%%v"
for /f "tokens=*" %%v in ('%PYCMD% -c "import sys;print(sys.version_info.minor)"') do set "PYMINOR=%%v"
echo [INFO]   python: %PYMAJOR%.%PYMINOR%  (using: %PYCMD%)
if %PYMAJOR% LSS 3 (
  echo [ERROR] Python too old: %PYMAJOR%.%PYMINOR% -- need 3.10 or newer
  goto :fail
)
if %PYMAJOR%==3 if %PYMINOR% LSS 10 (
  echo [ERROR] Python too old: %PYMAJOR%.%PYMINOR% -- need 3.10 or newer
  goto :fail
)

if %SKIPFE%==0 (
  where node >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] node not found. Install Node.js 18+ (20 LTS recommended).
    goto :fail
  )
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] npm not found (should ship with Node.js).
    goto :fail
  )
  for /f "tokens=*" %%v in ('node -v') do set "NODEV=%%v"
  for /f "tokens=*" %%v in ('npm -v') do set "NPMV=%%v"
  echo [INFO]   node: %NODEV%  npm: %NPMV%
)

REM ---------- required files ----------
if not exist "%BACKEND%\requirements.txt" (
  echo [ERROR] missing %BACKEND%\requirements.txt
  goto :fail
)
if not exist "%BACKEND%\.env.example" (
  echo [ERROR] missing %BACKEND%\.env.example
  goto :fail
)
if %SKIPFE%==0 if not exist "%FRONTEND%\package.json" (
  echo [ERROR] missing %FRONTEND%\package.json
  goto :fail
)

REM ---------- 2. .env ----------
if not exist "%BACKEND%\.env" (
  echo [INFO]  First run: copy .env.example -> .env
  copy /Y "%BACKEND%\.env.example" "%BACKEND%\.env" >nul
  echo [WARN]  Production: change JWT_SECRET and CORS_ORIGIN in .env
) else (
  echo [INFO]  .env exists, skip copy
)

REM ---------- 3. Python venv + pip ----------
cd /d "%BACKEND%"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "PIP=%BACKEND%\.venv\Scripts\pip.exe"
if not exist "%PY%" (
  echo [INFO]  Creating virtualenv .venv ...
  %PYCMD% -m venv .venv
  if not exist "%PY%" (
    echo [ERROR] venv creation failed
    goto :fail
  )
  echo [INFO]  Upgrading pip / setuptools / wheel ...
  "%PIP%" install --upgrade pip setuptools wheel
) else (
  echo [INFO]  .venv exists, skip creation
)
echo [INFO]  Installing Python deps (requirements.txt)...
"%PIP%" install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed
  goto :fail
)
echo [OK]    Python deps installed

REM ---------- 4. migrate (seeds admin/admin123 idempotently) ----------
echo [INFO]  Django check + migrate (first migrate seeds admin/admin123)...
"%PY%" manage.py check --fail-level ERROR
if errorlevel 1 (
  echo [ERROR] Django check failed
  goto :fail
)
"%PY%" manage.py migrate --noinput
if errorlevel 1 (
  echo [ERROR] migrate failed
  goto :fail
)
echo [OK]    Database migrated
"%PY%" -c "import os,sys;os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings');import django;django.setup();from apps.users.models import User;sys.stdout.write(str(User.objects.filter(username='admin').count()))" > "%TEMP%\gipfel_admincount.txt" 2>nul
set /p ADMINN=<"%TEMP%\gipfel_admincount.txt"
echo [INFO]   admin user count = %ADMINN%

REM ---------- 5. Frontend deps ----------
if %SKIPFE%==0 (
  cd /d "%FRONTEND%"
  if exist "%FRONTEND%\node_modules\.package-lock.json" (
    echo [INFO]  node_modules exists, npm install incremental...
  ) else (
    echo [INFO]  First install frontend deps from package.json...
  )
  npm install --no-audit --no-fund
  if errorlevel 1 (
    echo [ERROR] npm install failed
    goto :fail
  )
  echo [OK]    Frontend deps installed
)

REM ---------- done ----------
echo.
echo [OK]    Bootstrap finished! Next: double-click start-dev.bat
echo    1) Start Django + Vite + LogViewer: scripts\start-dev.bat
echo    2) Open http://localhost:5173  login admin / admin123 (force-change on first login)
echo.
cd /d "%~dp0"
echo [TIP]  Press any key to close this window...
pause
exit /b 0

:fail
echo.
echo [ERROR] Bootstrap FAILED. See messages above.
echo.
cd /d "%~dp0"
echo [TIP]  Press any key to close this window...
pause
exit /b 1
