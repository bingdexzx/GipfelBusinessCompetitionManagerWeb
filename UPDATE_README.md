# 更新和迁移指南

## 脚本说明

### 1. `update.sh` - 主更新脚本 (Linux)

用于更新应用程序、安装依赖、备份数据库。

**用法:**
```bash
# 普通更新（不迁移数据库）
sudo ./update.sh

# 更新并迁移到 PostgreSQL
sudo ./update.sh --migrate-db
```

**功能:**
- 停止所有服务
- 备份 SQLite 数据库
- 安装系统依赖
- 安装 Python 依赖
- 构建前端
- 运行数据库迁移
- 配置 Nginx
- 配置 Systemd 服务
- 启动服务
- 健康检查

### 2. `update.bat` - Windows 更新脚本

用于在 Windows 开发环境中更新应用程序。

**用法:**
```cmd
update.bat
```

**功能:**
- 备份数据库
- 安装 Python 依赖
- 构建前端
- 运行 Django 命令

### 3. `migrate_to_postgresql.sh` - PostgreSQL 迁移脚本

专门用于将 SQLite 数据迁移到 PostgreSQL。

**用法:**
```bash
sudo ./migrate_to_postgresql.sh
```

**功能:**
- 备份 SQLite 数据库
- 配置 PostgreSQL
- 创建 Django 配置
- 运行数据库迁移
- 导入数据
- 创建超级管理员
- 验证迁移

## 迁移到 PostgreSQL

### 前置条件

1. 安装 PostgreSQL:
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

2. 安装 Python 依赖:
```bash
pip install psycopg2-binary python-dotenv
```

### 迁移步骤

1. **备份数据:**
```bash
cd /opt/gipfel/backend
source .venv/bin/activate
python manage.py dumpdata --indent 2 > backup.json
```

2. **运行迁移脚本:**
```bash
sudo ./migrate_to_postgresql.sh
```

3. **验证迁移:**
```bash
# 检查数据库连接
cd /opt/gipfel/backend
source .venv/bin/activate
python manage.py check --database default

# 检查数据
python manage.py shell -c "from apps.users.models import User; print(f'用户数量: {User.objects.count()}')"
```

### 配置说明

迁移脚本会创建 `/opt/gipfel/backend/backend/.env` 文件，包含以下配置:

```env
# 数据库配置
DB_ENGINE=django.db.backends.postgresql
DB_NAME=gipfel
DB_USER=gipfel
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432

# Django 配置
DEBUG=False
SECRET_KEY=your_secret_key
ALLOWED_HOSTS=localhost,127.0.0.1
```

**重要:** 请修改 `DB_PASSWORD` 和 `SECRET_KEY` 为安全的值。

## 回滚方案

如果迁移失败，可以从备份恢复:

### 恢复 SQLite 数据库

```bash
# 停止服务
sudo systemctl stop gipfel-daphne

# 恢复数据库文件
cp /opt/gipfel/backups/db_before_migration_*.sqlite3 /opt/gipfel/backend/db.sqlite3

# 恢复配置
cp /opt/gipfel/backend/backend/settings.py.bak /opt/gipfel/backend/backend/settings.py

# 启动服务
sudo systemctl start gipfel-daphne
```

### 恢复 PostgreSQL 数据

```bash
# 删除 PostgreSQL 数据库
sudo -u postgres dropdb gipfel

# 重新运行迁移
sudo ./migrate_to_postgresql.sh
```

## 常见问题

### 1. 数据库连接失败

检查 PostgreSQL 服务是否运行:
```bash
sudo systemctl status postgresql
```

检查数据库配置:
```bash
cat /opt/gipfel/backend/backend/.env
```

### 2. 迁移后数据丢失

检查备份文件:
```bash
ls -la /opt/gipfel/backups/
```

重新导入数据:
```bash
cd /opt/gipfel/backend
source .venv/bin/activate
python manage.py loaddata /opt/gipfel/backups/data_before_migration_*.json
```

### 3. 权限问题

确保 PostgreSQL 用户有足够权限:
```bash
sudo -u postgres psql
GRANT ALL PRIVILEGES ON DATABASE gipfel TO gipfel;
ALTER USER gipfel CREATEDB;
\q
```

### 4. 性能问题

优化 PostgreSQL 配置 (`/etc/postgresql/15/main/postgresql.conf`):

```conf
# 连接配置
max_connections = 200
shared_buffers = 256MB
effective_cache_size = 768MB

# 查询优化
work_mem = 4MB
maintenance_work_mem = 128MB
random_page_cost = 1.1
effective_io_concurrency = 200
```

重启 PostgreSQL:
```bash
sudo systemctl restart postgresql
```

## 生产环境部署建议

### 1. 使用 Gunicorn + Nginx

```bash
# 安装 Gunicorn
pip install gunicorn

# 创建 Systemd 服务
sudo nano /etc/systemd/system/gipfel-gunicorn.service
```

服务配置:
```ini
[Unit]
Description=Gipfel Gunicorn
After=network.target postgresql.service

[Service]
User=root
Group=root
WorkingDirectory=/opt/gipfel/backend
ExecStart=/opt/gipfel/backend/.venv/bin/gunicorn \
    --workers 4 \
    --bind 0.0.0.0:8000 \
    --timeout 120 \
    backend.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

### 2. 使用连接池

安装 pgbouncer:
```bash
sudo apt install pgbouncer
```

配置 `/etc/pgbouncer/pgbouncer.ini`:
```ini
[databases]
gipfel = host=localhost port=5432 dbname=gipfel

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 20
```

### 3. 定期备份

创建备份脚本 `/opt/gipfel/backup.sh`:
```bash
#!/bin/bash
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_DIR="/opt/gipfel/backups"

# PostgreSQL 备份
pg_dump -U gipfel -h localhost gipfel > "$BACKUP_DIR/pg_backup_$TIMESTAMP.sql"

# 压缩
gzip "$BACKUP_DIR/pg_backup_$TIMESTAMP.sql"

# 删除7天前的备份
find "$BACKUP_DIR" -name "pg_backup_*.gz" -mtime +7 -delete
```

添加到 crontab:
```bash
crontab -e
# 每天凌晨3点备份
0 3 * * * /opt/gipfel/backup.sh
```

## 联系支持

如果遇到问题，请提供以下信息:
1. 错误日志: `journalctl -u gipfel-daphne -n 100`
2. 数据库状态: `sudo systemctl status postgresql`
3. 配置文件: `/opt/gipfel/backend/backend/.env` (隐藏密码)