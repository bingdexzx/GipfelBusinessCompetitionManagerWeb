# PostgreSQL 迁移指南

## 迁移可行性：✅ 完全兼容

经过代码审查，你的项目完全支持迁移到 PostgreSQL：
- 所有模型使用标准 Django ORM 字段
- 无 SQLite 特有语法
- 代码已为 PostgreSQL 做了准备（select_for_update 行锁）

## 第一步：安装 PostgreSQL

```bash
# Debian 12
sudo apt update
sudo apt install postgresql postgresql-client libpq-dev python3-dev

# 启动 PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# 检查状态
sudo systemctl status postgresql
```

## 第二步：创建数据库和用户

```bash
# 切换到 postgres 用户
sudo -u postgres psql

# 在 PostgreSQL 命令行中执行：
```

```sql
-- 创建数据库用户
CREATE USER gipfel WITH PASSWORD 'your_secure_password_here';

-- 创建数据库
CREATE DATABASE gipfel 
    OWNER gipfel
    ENCODING 'UTF8'
    LC_COLLATE 'zh_CN.UTF-8'
    LC_CTYPE 'zh_CN.UTF-8'
    TEMPLATE template0;

-- 授权
GRANT ALL PRIVILEGES ON DATABASE gipfel TO gipfel;

-- 退出
\q
```

## 第三步：安装 Python 依赖

```bash
cd /opt/gipfel/backend
source .venv/bin/activate

# 安装 PostgreSQL 适配器
pip install psycopg2-binary

# 或者编译安装（性能更好）
# pip install psycopg2

# 可选：安装连接池
pip install django-db-connection-pool[psycopg2]
```

## 第四步：修改 Django 配置

编辑 `backend/backend/settings.py`，替换数据库配置：

```python
# ==================== 数据库 ====================
# PostgreSQL 配置（替换 SQLite）
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "gipfel",
        "USER": "gipfel",
        "PASSWORD": "your_secure_password_here",  # 替换为实际密码
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "OPTIONS": {
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000",  # 30秒查询超时
        },
        "CONN_MAX_AGE": 600,  # 连接复用时间（秒）
    }
}

# 如果使用连接池（推荐，高并发场景）
# DATABASES = {
#     "default": {
#         "ENGINE": "dj_db_conn_pool.backends.postgresql",
#         "NAME": "gipfel",
#         "USER": "gipfel",
#         "PASSWORD": "your_secure_password_here",
#         "HOST": "127.0.0.1",
#         "PORT": "5432",
#         "POOL_OPTIONS": {
#             "POOL_SIZE": 20,  # 连接池大小
#             "MAX_OVERFLOW": 10,  # 最大溢出连接
#             "RECYCLE": 3600,  # 连接回收时间（秒）
#         },
#     }
# }
```

## 第五步：迁移数据

### 方法一：使用 Django dumpdata（推荐，小数据量）

```bash
cd /opt/gipfel/backend
source .venv/bin/activate

# 1. 备份 SQLite 数据库
cp db.sqlite3 db.sqlite3.backup.$(date +%Y%m%d_%H%M%S)

# 2. 导出所有数据
python manage.py dumpdata --indent 2 --output data_backup.json

# 3. 修改 settings.py 为 PostgreSQL（见第四步）

# 4. 运行数据库迁移
python manage.py migrate

# 5. 导入数据
python manage.py loaddata data_backup.json

# 6. 验证数据
python manage.py shell -c "
from apps.users.models import User
from apps.competitions.models import Competition
print(f'Users: {User.objects.count()}')
print(f'Competitions: {Competition.objects.count()}')
"
```

### 方法二：使用 pgloader（推荐，大数据量）

```bash
# 安装 pgloader
sudo apt install pgloader

# 创建迁移配置文件
cat > /tmp/pgloader.load << 'EOF'
LOAD DATABASE
    FROM sqlite:///opt/gipfel/backend/db.sqlite3
    INTO postgresql://gipfel:your_secure_password_here@localhost/gipfel

WITH include drop, create tables, create indexes, reset sequences

SET work_mem to '128MB', maintenance_work_mem to '512MB'

CAST type datetime to timestamptz
    drop default drop not null using zero-dates-to-null,
type integer to integer using row-id-seq

BEFORE LOAD DO
    $$ CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; $$

AFTER LOAD DO
    $$ ALTER DATABASE gipfel SET timezone TO 'Asia/Shanghai'; $$;
EOF

# 执行迁移
pgloader /tmp/pgloader.load
```

## 第六步：更新日志查看器配置

编辑 `backend/logviewer/logviewer/settings.py`：

```python
# 替换 SQLite 配置为 PostgreSQL
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "gipfel",
        "USER": "gipfel",
        "PASSWORD": "your_secure_password_here",
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }
}

# 删除或注释掉旧的 SQLite 路径配置
# DB_PATH = MAIN_DIR / "db.sqlite3"  # 注释掉
```

## 第七步：PostgreSQL 性能优化

编辑 `/etc/postgresql/15/main/postgresql.conf`：

```ini
# ==================== 连接设置 ====================
max_connections = 200
superuser_reserved_connections = 3

# ==================== 内存设置 ====================
# 共享缓冲区（建议物理内存的 25%）
shared_buffers = 4GB

# 工作内存（每个连接）
work_mem = 64MB

# 维护工作内存
maintenance_work_mem = 512MB

# 有效缓存大小（建议物理内存的 75%）
effective_cache_size = 12GB

# ==================== WAL 设置 ====================
wal_buffers = 64MB
checkpoint_completion_target = 0.9
max_wal_size = 2GB
min_wal_size = 1GB

# ==================== 查询优化 ====================
random_page_cost = 1.1  # SSD 存储
effective_io_concurrency = 200  # SSD 存储
default_statistics_target = 100

# ==================== 日志设置 ====================
log_min_duration_statement = 1000  # 记录超过1秒的查询
log_checkpoints = on
log_connections = on
log_disconnections = on
log_lock_waits = on

# ==================== 时区 ====================
timezone = 'Asia/Shanghai'
```

编辑 `/etc/postgresql/15/main/pg_hba.conf`：

```ini
# TYPE  DATABASE  USER  ADDRESS     METHOD
local   all       all               peer
host    gipfel    gipfel 127.0.0.1/32 md5
```

重启 PostgreSQL：

```bash
sudo systemctl restart postgresql
```

## 第八步：更新 Nginx 配置并重启服务

```bash
# 使用优化后的 Nginx 配置
sudo cp /opt/gipfel/deploy/nginx-gipfel-optimized.conf /etc/nginx/sites-available/gipfel
sudo ln -sf /etc/nginx/sites-available/gipfel /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启所有服务
sudo systemctl restart postgresql
sudo systemctl restart nginx
sudo systemctl restart gipfel-daphne
```

## 第九步：验证迁移

```bash
# 1. 检查数据库连接
cd /opt/gipfel/backend
source .venv/bin/activate
python manage.py dbshell

# 2. 在 PostgreSQL 命令行中检查
\dt  -- 列出所有表
SELECT count(*) FROM users;
SELECT count(*) FROM competitions;
\q

# 3. 运行 Django 检查
python manage.py check

# 4. 测试 API
curl http://127.0.0.1:8000/api/health

# 5. 压测验证
ab -n 1000 -c 200 http://your-domain.com/api/health
```

## 回滚方案

如果迁移失败，回滚到 SQLite：

```bash
# 1. 停止服务
sudo systemctl stop gipfel-daphne

# 2. 恢复 settings.py
cd /opt/gipfel/backend
# 编辑 settings.py，恢复 SQLite 配置

# 3. 恢复数据库备份
cp db.sqlite3.backup.YYYYMMDD_HHMMSS db.sqlite3

# 4. 重启服务
sudo systemctl start gipfel-daphne
```

## 迁移后优化

### 1. 连接池监控

```bash
# 查看活跃连接
sudo -u postgres psql -d gipfel -c "
SELECT count(*) as total_connections,
       state,
       usename
FROM pg_stat_activity
GROUP BY state, usename;
"
```

### 2. 慢查询分析

```bash
# 查看慢查询日志
sudo tail -f /var/log/postgresql/postgresql-15-main.log

# 或使用 pg_stat_statements
sudo -u postgres psql -d gipfel -c "
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 20;
"
```

### 3. 表膨胀检查

```bash
sudo -u postgres psql -d gipfel -c "
SELECT schemaname, tablename, 
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
       n_dead_tup, n_live_tup
FROM pg_stat_user_tables
ORDER BY n_dead_tup DESC;
"
```

## 预期效果

| 指标 | SQLite（当前） | PostgreSQL（迁移后） | 提升 |
|------|---------------|---------------------|------|
| 并发能力 | ~50 | 500+ | 10倍 |
| 写入锁等待 | 频繁 | 无 | 完全消除 |
| 平均响应时间 | 1-3秒 | 100-300ms | 5-10倍 |
| 数据库锁错误 | 常见 | 无 | 完全消除 |
| CPU 利用率 | 26%（瓶颈在锁） | 60-80%（充分利用） | 更高效 |

## 常见问题

### Q1: 迁移后数据丢失？

A: 使用 `dumpdata` 导出的数据是完整的 JSON，可以多次导入。如果担心，先在本地测试。

### Q2: 迁移时间太长？

A: 小数据量（<1GB）通常 5-10 分钟。大数据量使用 pgloader 更快。

### Q3: 连接数不够？

A: 修改 `postgresql.conf` 的 `max_connections`，并确保 Nginx 的 `keepalive` 设置合理。

### Q4: 如何监控 PostgreSQL？

A: 使用 `pg_stat_activity` 和 `pg_stat_statements`，或安装 pgAdmin。

## 联系支持

如果迁移过程中遇到问题，请提供：
1. PostgreSQL 日志：`/var/log/postgresql/postgresql-15-main.log`
2. Django 日志：`/opt/gipfel/backend/logs/gipfel.log`
3. 错误截图

## 迁移检查清单

- [ ] PostgreSQL 安装完成
- [ ] 数据库和用户创建完成
- [ ] Python 依赖安装完成
- [ ] settings.py 配置更新
- [ ] 数据导出完成
- [ ] 数据库迁移完成
- [ ] 数据导入完成
- [ ] 日志查看器配置更新
- [ ] PostgreSQL 性能优化完成
- [ ] Nginx 配置更新完成
- [ ] 所有服务重启完成
- [ ] API 测试通过
- [ ] 压测验证通过