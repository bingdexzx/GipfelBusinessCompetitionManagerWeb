# MySQL 迁移指南 - 解决并发瓶颈

## 为什么迁移？

SQLite 的问题：
- 写入时锁定整个数据库
- 200-500 并发会导致严重的 "database is locked" 错误
- 60秒超时排队，前端直接超时

MySQL 的优势：
- 行级锁，支持高并发读写
- 连接池，减少连接开销
- 更好的性能和稳定性

## 迁移步骤

### 1. 安装 MySQL

```bash
# Debian 12
sudo apt update
sudo apt install mysql-server mysql-client libmysqlclient-dev python3-dev

# 启动 MySQL
sudo systemctl start mysql
sudo systemctl enable mysql

# 安全初始化
sudo mysql_secure_installation
```

### 2. 创建数据库和用户

```sql
-- 登录 MySQL
sudo mysql -u root

-- 创建数据库
CREATE DATABASE gipfel CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 创建用户（替换 your_password）
CREATE USER 'gipfel'@'localhost' IDENTIFIED BY 'your_secure_password';

-- 授权
GRANT ALL PRIVILEGES ON gipfel.* TO 'gipfel'@'localhost';
FLUSH PRIVILEGES;

-- 退出
EXIT;
```

### 3. 安装 Python 依赖

```bash
cd /opt/gipfel/backend
source .venv/bin/activate

# 安装 MySQL 客户端
pip install mysqlclient

# 安装连接池（可选，推荐）
pip install django-db-connection-pool[mysql]
```

### 4. 修改 Django 配置

编辑 `backend/settings.py`：

```python
# ========== MySQL 配置 ==========
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'gipfel',
        'USER': 'gipfel',
        'PASSWORD': 'your_secure_password',
        'HOST': '127.0.0.1',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'connect_timeout': 10,
            'read_timeout': 30,
            'write_timeout': 30,
        },
        'CONN_MAX_AGE': 600,  # 连接复用时间（秒）
    }
}

# 如果使用连接池（推荐）
# DATABASES = {
#     'default': {
#         'ENGINE': 'dj_db_conn_pool.backends.mysql',
#         'NAME': 'gipfel',
#         'USER': 'gipfel',
#         'PASSWORD': 'your_secure_password',
#         'HOST': '127.0.0.1',
#         'PORT': '3306',
#         'POOL_OPTIONS': {
#             'POOL_SIZE': 20,  # 连接池大小
#             'MAX_OVERFLOW': 10,  # 最大溢出连接
#             'RECYCLE': 3600,  # 连接回收时间
#         },
#     }
# }
```

### 5. 迁移数据

```bash
cd /opt/gipfel/backend
source .venv/bin/activate

# 1. 导出 SQLite 数据
python manage.py dumpdata --indent 2 > data_backup.json

# 2. 运行 MySQL 迁移
python manage.py migrate

# 3. 导入数据
python manage.py loaddata data_backup.json

# 4. 创建超级管理员（如果需要）
python manage.py createsuperuser
```

### 6. 验证迁移

```bash
# 测试数据库连接
python manage.py dbshell

# 检查数据
python manage.py shell
>>> from apps.users.models import User
>>> User.objects.count()
```

### 7. 更新 Nginx 配置并重启

```bash
# 复制优化后的 Nginx 配置
sudo cp deploy/nginx-gipfel-optimized.conf /etc/nginx/sites-available/gipfel
sudo ln -sf /etc/nginx/sites-available/gipfel /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重启服务
sudo systemctl restart nginx
sudo systemctl restart gipfel-daphne
```

## MySQL 性能优化

编辑 `/etc/mysql/mysql.conf.d/mysqld.cnf`：

```ini
[mysqld]
# 基础设置
max_connections = 500
max_connect_errors = 100
wait_timeout = 600
interactive_timeout = 600

# InnoDB 设置
innodb_buffer_pool_size = 4G  # 内存的 50-70%
innodb_log_file_size = 256M
innodb_flush_log_at_trx_commit = 2
innodb_flush_method = O_DIRECT

# 查询缓存（MySQL 8.0 已移除）
# query_cache_type = 1
# query_cache_size = 64M

# 慢查询日志
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 2

# 连接设置
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
```

重启 MySQL：
```bash
sudo systemctl restart mysql
```

## 监控命令

```bash
# 查看连接数
mysqladmin -u gipfel -p status

# 查看进程列表
mysql -u gipfel -p -e "SHOW PROCESSLIST;"

# 查看 InnoDB 状态
mysql -u gipfel -p -e "SHOW ENGINE INNODB STATUS\G"
```

## 回滚方案

如果迁移失败，可以回滚到 SQLite：

```python
# 恢复 settings.py 中的 SQLite 配置
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```

然后重启服务即可。

## 预期效果

迁移到 MySQL 后：
- 并发能力：从 ~50 提升到 500+
- 响应时间：从 1-3秒 降低到 100-300ms
- 锁等待：完全消除
- 稳定性：大幅提升

## 需要帮助？

如果迁移过程中遇到问题，可以：
1. 查看 Django 日志：`tail -f /opt/gipfel/backend/logs/gipfel.log`
2. 查看 MySQL 日志：`tail -f /var/log/mysql/error.log`
3. 检查 Nginx 错误：`tail -f /var/log/nginx/error.log`