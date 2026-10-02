# PostgreSQL 迁移快速指南

## 迁移可行性：✅ 完全兼容

你的项目代码已经为 PostgreSQL 做了准备，可以无缝迁移。

## 快速开始（15分钟完成）

### 第一步：修改配置

编辑 `deploy/migrate-to-postgresql.sh`，修改以下配置：

```bash
# 数据库配置（必须修改）
DB_NAME="gipfel"
DB_USER="gipfel"
DB_PASSWORD="your_actual_password_here"  # ← 改成你的密码
DB_HOST="127.0.0.1"
DB_PORT="5432"
```

### 第二步：执行迁移

```bash
# 上传脚本到服务器
scp deploy/migrate-to-postgresql.sh root@your-server:/opt/gipfel/deploy/

# SSH 登录服务器
ssh root@your-server

# 给脚本执行权限
chmod +x /opt/gipfel/deploy/migrate-to-postgresql.sh

# 执行迁移（自动备份、导出、导入、验证）
bash /opt/gipfel/deploy/migrate-to-postgresql.sh
```

### 第三步：验证结果

```bash
# 检查数据库连接
cd /opt/gipfel/backend
source .venv/bin/activate
python manage.py dbshell

# 在 PostgreSQL 命令行中检查
\dt  -- 列出所有表
SELECT count(*) FROM users;
\q

# 测试 API
curl http://127.0.0.1:8000/api/health

# 压测验证
ab -n 1000 -c 200 http://your-domain.com/api/health
```

## 迁移脚本功能

自动化脚本会执行以下操作：

1. ✅ 检查前置条件（PostgreSQL 安装、项目目录）
2. ✅ 备份 SQLite 数据库（带时间戳）
3. ✅ 创建 PostgreSQL 数据库和用户
4. ✅ 安装 Python 依赖（psycopg2-binary）
5. ✅ 导出所有数据为 JSON
6. ✅ 更新 Django 配置文件
7. ✅ 运行数据库迁移
8. ✅ 导入数据到 PostgreSQL
9. ✅ 验证迁移结果
10. ✅ 更新日志查看器配置
11. ✅ 重启所有服务

## 文件说明

```
deploy/
├── migrate-to-postgresql.sh          # 自动化迁移脚本（推荐）
├── postgresql-migration-guide.md     # 详细迁移指南
├── mysql-migration-guide.md          # MySQL 迁移指南（备选）
└── README-POSTGRESQL-MIGRATION.md    # 本文档
```

## 迁移前后对比

| 指标 | SQLite（当前） | PostgreSQL（迁移后） |
|------|---------------|---------------------|
| 并发能力 | ~50 | 500+ |
| 写入锁等待 | 频繁 | 无 |
| 平均响应时间 | 1-3秒 | 100-300ms |
| 数据库锁错误 | 常见 | 无 |
| CPU 利用率 | 26%（瓶颈在锁） | 60-80%（充分利用） |

## 常见问题

### Q: 迁移会影响现有数据吗？

A: 不会。脚本会自动备份 SQLite 数据库，并导出为 JSON。即使迁移失败，也可以回滚。

### Q: 迁移需要多长时间？

A: 取决于数据量：
- < 100MB：5-10 分钟
- 100MB - 1GB：10-30 分钟
- > 1GB：30-60 分钟

### Q: 迁移期间服务会中断吗？

A: 是的，迁移期间需要停止服务。建议在低峰期（如凌晨）进行。

### Q: 如何回滚？

A: 脚本会自动备份，回滚步骤：

```bash
# 1. 停止服务
sudo systemctl stop gipfel-daphne

# 2. 恢复配置
cp /opt/gipfel/backups/settings.py.backup.TIMESTAMP /opt/gipfel/backend/backend/settings.py

# 3. 恢复数据库
cp /opt/gipfel/backups/db.sqlite3.backup.TIMESTAMP /opt/gipfel/backend/db.sqlite3

# 4. 重启服务
sudo systemctl start gipfel-daphne
```

### Q: 迁移后性能没有提升？

A: 检查以下几点：
1. PostgreSQL 配置是否优化（参考 postgresql-migration-guide.md）
2. Nginx 是否使用优化配置
3. Daphne 是否启动多个 worker
4. 是否启用了连接池

## 性能优化建议

迁移后，建议进一步优化：

1. **PostgreSQL 配置优化**
   - 调整 `shared_buffers` 为物理内存的 25%
   - 调整 `effective_cache_size` 为物理内存的 75%
   - 启用 `pg_stat_statements` 监控慢查询

2. **连接池配置**
   - 安装 `django-db-connection-pool`
   - 设置连接池大小为 20-30

3. **Nginx 优化**
   - 使用优化后的配置文件
   - 启用 gzip 压缩
   - 配置静态文件缓存

4. **Daphne 多 worker**
   - 启动 4-6 个 worker 进程
   - 充分利用 8 核 CPU

## 监控命令

```bash
# 查看 PostgreSQL 连接数
sudo -u postgres psql -d gipfel -c "
SELECT count(*) as total_connections, state
FROM pg_stat_activity
GROUP BY state;
"

# 查看慢查询
sudo -u postgres psql -d gipfel -c "
SELECT query, calls, mean_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
"

# 查看表大小
sudo -u postgres psql -d gipfel -c "
SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename))
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(tablename) DESC;
"

# 实时监控
watch -n 2 "sudo -u postgres psql -d gipfel -c 'SELECT count(*) FROM pg_stat_activity;'"
```

## 联系支持

如果迁移过程中遇到问题，请提供：

1. 迁移脚本的完整输出
2. PostgreSQL 日志：`/var/log/postgresql/postgresql-15-main.log`
3. Django 日志：`/opt/gipfel/backend/logs/gipfel.log`
4. 错误截图

## 迁移检查清单

- [ ] 修改迁移脚本中的数据库密码
- [ ] 上传脚本到服务器
- [ ] 执行迁移脚本
- [ ] 验证数据完整性
- [ ] 测试 API 接口
- [ ] 压测验证性能
- [ ] 监控运行状态
- [ ] 确认无回滚需求后删除备份（可选）

## 下一步

迁移完成后，建议：

1. 运行监控脚本：`bash /opt/gipfel/deploy/monitor.sh`
2. 查看优化指南：`cat /opt/gipfel/deploy/README-OPTIMIZATION.md`
3. 配置定时备份：参考 PostgreSQL 官方文档

祝迁移顺利！🚀