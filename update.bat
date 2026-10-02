@echo off
REM ============================================================
REM Gipfel 业务竞赛管理系统 - Windows 更新脚本
REM 用法: update.bat [--migrate-db]
REM ============================================================

setlocal enabledelayedexpansion

set APP_DIR=C:\gipfel
set BACKEND_DIR=%APP_DIR%\backend
set FRONTEND_DIR=%APP_DIR%\frontend
set BACKUP_DIR=%APP_DIR%\backups
set VENV_DIR=%BACKEND_DIR%\.venv

REM 颜色代码
set RED=[91m
set GREEN=[92m
set YELLOW=[93m
set BLUE=[94m
set NC=[0m

echo %GREEN%============================================================
echo  Gipfel 业务竞赛管理系统 - 更新脚本
echo ============================================================%NC%
echo.

REM 检查参数
set MIGRATE_DB=false
if "%1"=="--migrate-db" set MIGRATE_DB=true

REM ==================== 备份数据库 ====================
echo %BLUE%[%time%] 正在备份数据库...%NC%
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

set TIMESTAMP=%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%

if exist "%BACKEND_DIR%\db.sqlite3" (
    copy "%BACKEND_DIR%\db.sqlite3" "%BACKUP_DIR%\db_backup_%TIMESTAMP%.sqlite3"
    echo %GREEN%数据库已备份到: %BACKUP_DIR%\db_backup_%TIMESTAMP%.sqlite3%NC%
    
    REM 导出 JSON 数据
    cd /d "%BACKEND_DIR%"
    call "%VENV_DIR%\Scripts\activate.bat"
    python manage.py dumpdata --indent 2 > "%BACKUP_DIR%\data_backup_%TIMESTAMP%.json"
    echo %GREEN%数据已导出到: %BACKUP_DIR%\data_backup_%TIMESTAMP%.json%NC%
) else (
    echo %YELLOW%未找到数据库文件%NC%
)

REM ==================== 安装 Python 依赖 ====================
echo %BLUE%[%time%] 正在安装 Python 依赖...%NC%
cd /d "%BACKEND_DIR%"

REM 创建虚拟环境（如果不存在）
if not exist "%VENV_DIR%" (
    python -m venv "%VENV_DIR%"
    echo %GREEN%已创建虚拟环境%NC%
)

REM 激活虚拟环境并安装依赖
call "%VENV_DIR%\Scripts\activate.bat"
pip install --upgrade pip
pip install -r requirements.txt
echo %GREEN%Python 依赖安装完成%NC%

REM ==================== 构建前端 ====================
echo %BLUE%[%time%] 正在构建前端...%NC%
cd /d "%FRONTEND_DIR%"

where pnpm >nul 2>&1
if %errorlevel% equ 0 (
    pnpm install --frozen-lockfile
    pnpm run build
) else (
    where npm >nul 2>&1
    if %errorlevel% equ 0 (
        npm ci
        npm run build
    ) else (
        echo %RED%未找到 npm 或 pnpm，请先安装 Node.js%NC%
        exit /b 1
    )
)
echo %GREEN%前端构建完成%NC%

REM ==================== 运行 Django 命令 ====================
echo %BLUE%[%time%] 正在运行 Django 命令...%NC%
cd /d "%BACKEND_DIR%"
call "%VENV_DIR%\Scripts\activate.bat"

REM 收集静态文件
python manage.py collectstatic --noinput

REM 运行迁移
python manage.py migrate
echo %GREEN%Django 命令执行完成%NC%

REM ==================== 完成 ====================
echo.
echo %GREEN%============================================================
echo  更新完成！
echo ============================================================%NC%
echo.
echo 备份位置: %BACKUP_DIR%
echo.
echo 启动后端: cd %BACKEND_DIR% ^&^& python manage.py runserver
echo 启动前端: cd %FRONTEND_DIR% ^&^& npm run dev
echo.
echo %GREEN%============================================================%NC%

pause