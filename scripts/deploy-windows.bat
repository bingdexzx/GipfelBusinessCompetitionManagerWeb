@echo off
REM ========================================================================
REM  Gipfel - PRODUCTION - Deploy to local folder (self-contained batch)
REM  RUN AS ADMINISTRATOR.
REM  Pure ASCII file (English comments only).
REM
REM  Usage (admin CMD):
REM      deploy-windows.bat  C:\gipfel  8000  80  1
REM        arg1 = InstallDir     (default C:\gipfel)
REM        arg2 = BackendPort    (default 8000)
REM        arg3 = FrontendPort   (default 80)
REM        arg4 = WithService    (1 = register GipfelBackend via nssm; default 0)
REM
REM  Steps:
REM    1. Check Python/Node/npm + required files
REM    2. Robocopy-mirror code to InstallDir (back up old db/uploads/.env)
REM    3. venv + pip; on first deploy generate .env with random JWT_SECRET
REM    4. manage.py check + migrate; force-change default admin/admin123
REM    5. npm ci + build -> frontend-dist
REM    6. [-WithService 1] register Windows service GipfelBackend via nssm
REM    7. [-no skip] optional IIS site (best-effort inline PowerShell)
REM ========================================================================
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

REM --- admin check (must run elevated) ---
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo [ERROR] This script requires ADMINISTRATOR rights.
  echo         Open CMD -^> right-click -^> Run as administrator, then re-run.
  echo.
  pause
  exit /b 1
)

set "PROJECTROOT=%~dp0.."
set "INSTALLDIR=%~1"
if "%INSTALLDIR%"=="" set "INSTALLDIR=C:\gipfel"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8000"
set "FPORT=%~3"
if "%FPORT%"=="" set "FPORT=80"
set "WITHSVC=%~4"
if "%WITHSVC%"=="" set "WITHSVC=0"
set "ADMINPW=Admin@2026"
set "SKIPIIS=0"
set "FORCEOVERWRITE=1"

set "TARGETBACKEND=%INSTALLDIR%\backend"
set "TARGETFRONTEND=%INSTALLDIR%\frontend"
set "FRONTENDDIST=%INSTALLDIR%\frontend-dist"

REM ---------- 1. environment checks ----------
echo [INFO]  Checking environment...
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python not found.
  goto :fail
)
where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] node not found.
  goto :fail
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found.
  goto :fail
)
if not exist "%PROJECTROOT%\backend\requirements.txt" (
  echo [ERROR] missing backend\requirements.txt
  goto :fail
)
if not exist "%PROJECTROOT%\backend\.env.example" (
  echo [ERROR] missing backend\.env.example
  goto :fail
)
if not exist "%PROJECTROOT%\frontend\package.json" (
  echo [ERROR] missing frontend\package.json
  goto :fail
)
if not exist "%PROJECTROOT%\deploy\gipfel.service" (
  echo [ERROR] missing deploy\gipfel.service
  goto :fail
)

REM ---------- 2. backup old data + sync code ----------
if exist "%TARGETBACKEND%" (
  set "STAMP=%DATE:/=%_%TIME::=%"
  set "STAMP=!STAMP: =0!"
  set "BACKUPDIR=%INSTALLDIR%\_backup\!STAMP!"
  if exist "%TARGETBACKEND%\db.sqlite3" (
    mkdir "%BACKUPDIR%" 2>nul
    copy /Y "%TARGETBACKEND%\db.sqlite3" "%BACKUPDIR%\db.sqlite3" >nul
  )
  if exist "%TARGETBACKEND%\uploads" (
    mkdir "%BACKUPDIR%" 2>nul
    xcopy /E /I /Y "%TARGETBACKEND%\uploads" "%BACKUPDIR%\uploads" >nul
  )
  if exist "%TARGETBACKEND%\.env" (
    mkdir "%BACKUPDIR%" 2>nul
    copy /Y "%TARGETBACKEND%\.env" "%BACKUPDIR%\.env" >nul
  )
  echo [OK]    Backed up old data to !BACKUPDIR!
)

mkdir "%INSTALLDIR%" 2>nul
echo [INFO]  Syncing code to %INSTALLDIR% ...
call :robocopy_sync "%PROJECTROOT%\backend" "%TARGETBACKEND%"
call :robocopy_sync "%PROJECTROOT%\frontend" "%TARGETFRONTEND%"
call :robocopy_sync "%PROJECTROOT%\deploy" "%INSTALLDIR%\deploy"

REM restore uploads / .env from backup
if exist "%BACKUPDIR%\uploads" xcopy /E /I /Y "%BACKUPDIR%\uploads" "%TARGETBACKEND%\uploads" >nul
if exist "%BACKUPDIR%\.env" if not exist "%TARGETBACKEND%\.env" copy /Y "%BACKUPDIR%\.env" "%TARGETBACKEND%\.env" >nul

REM ---------- 3. venv + pip ----------
cd /d "%TARGETBACKEND%"
set "PY=%TARGETBACKEND%\.venv\Scripts\python.exe"
set "PIP=%TARGETBACKEND%\.venv\Scripts\pip.exe"
if not exist "%PY%" (
  echo [INFO]  Creating Python virtualenv
  python -m venv .venv
  if not exist "%PY%" (
    echo [ERROR] venv creation failed
    goto :fail
  )
  "%PIP%" install --upgrade pip setuptools wheel
)
echo [INFO]  pip install -r requirements.txt
"%PIP%" install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] pip install failed
  goto :fail
)
echo [OK]    Python deps done

REM ---------- .env first generation ----------
set "ENVFILE=%TARGETBACKEND%\.env"
if not exist "%ENVFILE%" (
  copy /Y "%TARGETBACKEND%\.env.example" "%ENVFILE%" >nul
  REM generate 40-char alphanumeric JWT secret via inline PowerShell
  for /f "tokens=*" %%s in ('powershell -NoProfile -Command "$s=-join((1..40)|%%{([char[]]((48..57)+(65..90)+(97..122))|Get-Random)});$s"') do set "JWTSECRET=%%s"
  powershell -NoProfile -Command "(Get-Content '%ENVFILE%') -replace '(?m)^JWT_SECRET=.*','JWT_SECRET=!JWTSECRET!' -replace '(?m)^DEBUG=true','DEBUG=false' | Set-Content -NoNewline '%ENVFILE%'"
  echo [INFO]  .env generated with random JWT_SECRET, DEBUG=false
)

REM uploads / logs dirs
mkdir "%TARGETBACKEND%\uploads" 2>nul
mkdir "%TARGETBACKEND%\logs" 2>nul
echo [OK]    Code + venv ready

REM ---------- 4. migrate + force admin password ----------
echo [INFO]  Django check + migrate...
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
echo [INFO]  Ensuring default admin password is not admin123...
"%PY%" -c "import os,sys; os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.settings'); import django; django.setup(); from apps.users.models import User; import bcrypt; u=User.objects.filter(username='admin').first(); pw=sys.argv[1]; if u and u.check_password('admin123'): u.password=bcrypt.hashpw(pw.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8'); u.must_change_password=False; u.save(update_fields=['password','must_change_password','updated_at']); print('ADMIN_PASSWORD_UPDATED') else: print('ADMIN_PASSWORD_UNCHANGED')" "%ADMINPW%"

REM ---------- 5. frontend build ----------
echo [INFO]  Frontend: npm ci -> build ...
cd /d "%TARGETFRONTEND%"
npm ci --no-audit --no-fund
if errorlevel 1 (
  echo [ERROR] npm ci failed
  goto :fail
)
npm run build
if errorlevel 1 (
  echo [ERROR] npm run build failed
  goto :fail
)
if exist "%FRONTENDDIST%" rmdir /s /q "%FRONTENDDIST%"
mkdir "%FRONTENDDIST%"
xcopy /E /I /Y "%TARGETFRONTEND%\dist\*" "%FRONTENDDIST%"
echo [OK]    Frontend built -> %FRONTENDDIST%

REM ---------- 6. register Windows service via nssm ----------
if "%WITHSVC%"=="1" (
  where nssm >nul 2>nul
  if errorlevel 1 (
    where choco >nul 2>nul
    if not errorlevel 1 (
      echo [INFO]  Installing nssm via choco...
      choco install nssm -y --no-progress
    )
    where nssm >nul 2>nul
    if errorlevel 1 (
      echo [WARN]  nssm not found; skipping service registration.
      goto :after_service
    )
  )
  set "DAPHNE=%TARGETBACKEND%\.venv\Scripts\daphne.exe"
  if not exist "%DAPHNE%" (
    echo [ERROR] %DAPHNE% not found - daphne not installed
    goto :fail
  )
  sc query GipfelBackend >nul 2>nul
  if not errorlevel 1 (
    echo [INFO]  Removing old GipfelBackend service...
    net stop GipfelBackend >nul 2>nul
    nssm remove GipfelBackend confirm >nul 2>nul
    timeout /T 2 /NOBREAK >nul
  )
  echo [INFO]  Installing service GipfelBackend...
  nssm install GipfelBackend "%DAPHNE%" "-b 127.0.0.1 -p %PORT% --proxy-headers backend.asgi:application"
  nssm set GipfelBackend AppDirectory "%TARGETBACKEND%"
  nssm set GipfelBackend AppStdout "%TARGETBACKEND%\logs\service-stdout.log"
  nssm set GipfelBackend AppStderr "%TARGETBACKEND%\logs\service-stderr.log"
  nssm set GipfelBackend AppRotateFiles 1
  nssm set GipfelBackend Start SERVICE_AUTO_START
  nssm set GipfelBackend DisplayName "Gipfel Business Competition Manager Backend"
  nssm set GipfelBackend Description "Django daphne ASGI server + Socket.IO"
  net start GipfelBackend
  echo [OK]    Service GipfelBackend registered and started.
)
:after_service

REM ---------- 7. optional IIS site ----------
if "%SKIPIIS%"=="0" (
  powershell -NoProfile -Command "if (Get-Command Get-IISSite -ErrorAction SilentlyContinue) { Import-Module WebAdministration -ErrorAction SilentlyContinue; if (-not (Get-IISSite 'Gipfel' -ErrorAction SilentlyContinue)) { try { New-WebAppPool -Name 'GipfelPool' -Force | Out-Null; New-Website -Name 'Gipfel' -PhysicalPath '%FRONTENDDIST%' -Port %FPORT% -ApplicationPool 'GipfelPool' -Force | Out-Null; Start-Website -Name 'Gipfel'; Write-Host 'IIS site Gipfel created.' } catch { Write-Host ('IIS site creation failed: ' + $_.Exception.Message) } } else { Write-Host 'IIS site Gipfel already exists.' } } else { Write-Host 'IIS/Get-IISSite not detected; skipping IIS site.' }"
)

REM ---------- done ----------
echo.
echo [OK]    Deploy finished!
echo    Install dir   : %INSTALLDIR%
echo    Backend API   : http://127.0.0.1:%PORT%/api/health
echo    Frontend dist : %FRONTENDDIST%
echo    Default admin : admin / %ADMINPW%
echo    Service       : sc query GipfelBackend
echo    Log dir       : %TARGETBACKEND%\logs
cd /d "%~dp0"
exit /b 0

:fail
echo.
echo [ERROR] Deploy FAILED. See messages above.
cd /d "%~dp0"
exit /b 1

REM ========================================================================
REM  Subroutine: robocopy mirror sync with dev-artifact exclusions
REM ========================================================================
:robocopy_sync
set "SRC=%~1"
set "DST=%~2"
robocopy "%SRC%" "%DST%" /MIR /NFL /NDL /NJH /NJS /R:2 /W:1 /XD .venv __pycache__ node_modules dist logs uploads _backup /XF *.pyc *.pyo db.sqlite3 .env .DS_Store
if errorlevel 8 (
  echo [ERROR] robocopy failed, code %errorlevel%
  goto :fail
)
goto :eof
