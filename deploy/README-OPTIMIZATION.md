# 并发性能优化指南

## 问题诊断

根据你的服务器监控数据：
- **CPU**: 26.44%（8核，负载很轻）
- **内存**: 1.7GB/16GB（使用率 10%）
- **网络**: 30Mbps（足够）
- **当前并发**: 200-500 用户

**问题根源**：不是硬件不足，而是软件配置和架构问题。

## 快速解决方案

### 方案一：快速优化（5分钟，不换数据库）

适合：临时活动，需要立即见效

```bash
# 上传优化脚本到服务器
scp deploy/quick-optimize.sh root@your-server:/opt/gipfel/deploy/

# 在服务器上执行
ssh root@your-server
chmod +x /opt/gipfel/deploy/quick-optimize.sh
bash /opt/gipfel/deploy/quick-optimize.sh
```

**预期效果**：
- 并发能力：从 ~50 提升到 200-300
- 响应时间：降低 30-50%
- 超时错误：大幅减少

### 方案二：完整优化（30分钟，迁移到 MySQL）

适合：长期运营，需要稳定支持 500+ 并发

```bash
# 参考迁移指南
cat deploy/mysql-migration-guide.md
```

**预期效果**：
- 并发能力：500+ 稳定运行
- 响应时间：100-300ms
- 完全消除锁等待

## 文件说明

```
deploy/
├── nginx-gipfel-optimized.conf  # Nginx 优化配置
├── start-daphne-workers.sh      # Daphne 多 worker 启动脚本
├── gipfel-daphne.service        # systemd 服务文件
├── quick-optimize.sh            # 快速优化脚本
├── mysql-migration-guide.md     # MySQL 迁移指南
└── README-OPTIMIZATION.md       # 本文档
```

## 优化原理

### 1. SQLite WAL 模式

默认 SQLite 使用回滚日志，写入时锁定整个数据库。

启用 WAL（Write-Ahead Logging）模式后：
- 读写可以并发
- 写入不再阻塞读取
- 性能提升 2-5 倍

### 2. Nginx 连接优化

- **连接池**：复用后端连接，减少 TCP 握手
- **缓冲区**：减少后端进程等待时间
- **限流**：防止恶意请求耗尽资源
- **超时设置**：合理设置，避免僵尸连接

### 3. 多 Worker 进程

Daphne 默认单进程，无法利用多核 CPU。

启动 4 个 worker：
- 充分利用 8 核 CPU
- 单个 worker 阻塞不影响其他
- 自动负载均衡

### 4. 系统参数优化

- **文件描述符**：增加最大打开文件数
- **TCP 参数**：优化网络连接复用
- **连接队列**：增加等待队列长度

## 监控和调优

### 实时监控

```bash
# 查看 Daphne 进程状态
ps aux | grep daphne

# 查看连接数
ss -s

# 查看 Nginx 状态
systemctl status nginx

# 实时日志
tail -f /var/log/daphne/*.log

# 查看系统负载
htop
```

### 性能测试

```bash
# 安装压测工具
apt install apache2-utils

# 测试并发性能
ab -n 1000 -c 200 http://your-domain.com/api/health

# 查看结果
# - Requests per second: 每秒请求数
# - Time per request: 平均响应时间
# - Failed requests: 失败请求数
```

### 调优建议

如果仍有超时，按以下顺序调整：

1. **增加 Daphne worker 数量**
   ```bash
   # 修改 start-daphne-workers.sh
   WORKERS=6  # 从 4 增加到 6
   ```

2. **调整 Nginx 超时**
   ```nginx
   proxy_read_timeout 180s;  # 从 120s 增加
   ```

3. **调整 SQLite 超时**
   ```python
   # settings.py
   'timeout': 120,  # 从 60 增加
   ```

4. **迁移到 MySQL**（终极方案）

## 常见问题

### Q: 优化后仍有超时？

A: 可能原因：
1. 数据库查询太慢 → 检查慢查询日志
2. 单个请求处理时间太长 → 优化业务逻辑
3. 数据库锁竞争 → 迁移到 MySQL

### Q: 如何确认优化生效？

A: 检查以下指标：
```bash
# 1. 检查 SQLite WAL 模式
python manage.py dbshell
> PRAGMA journal_mode;  # 应该返回 "wal"

# 2. 检查 Daphne worker 数量
ps aux | grep daphne | wc -l  # 应该返回 5（4个worker + 1个grep）

# 3. 检查 Nginx 连接数
ss -s  # 查看 TCP 连接数
```

### Q: 什么时候需要迁移到 MySQL？

A: 以下情况建议迁移：
- 持续出现 "database is locked" 错误
- 并发超过 300 时响应明显变慢
- 需要长期稳定运营
- 数据量超过 1GB

## 联系支持

如果优化后仍有问题，请提供：
1. 服务器监控截图
2. Daphne 错误日志
3. Nginx 错误日志
4. 压测结果（ab 命令输出）

## 更新日志

- 2024-10-02: 初始版本，包含快速优化和完整迁移指南