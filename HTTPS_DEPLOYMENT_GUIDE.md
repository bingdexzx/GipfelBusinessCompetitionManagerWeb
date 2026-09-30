# HTTPS部署指南

## 问题描述

审计日志提示"身份认证信息未提供"的问题，主要原因是HTTPS部署环境下CSRF cookie的安全设置不完整。

## 根本原因

1. **CSRF Cookie安全设置缺失**：
   - 在HTTPS部署时，浏览器要求`Secure`标记的cookie只能通过HTTPS传输
   - 原配置中`CSRF_COOKIE_SECURE`和`SESSION_COOKIE_SECURE`没有正确设置

2. **部署配置不完整**：
   - 虽然添加了域名、反向代理和证书，但没有配置相关的环境变量
   - 导致Django的CSRF中间件无法正确处理HTTPS请求

## 解决方案

### 1. 自动修复（推荐）

运行部署脚本或更新脚本，脚本会自动配置所需的环境变量：

```bash
# 新部署
sudo bash scripts/deploy-linux.sh --domain your-domain.com --with-nginx --origin-cert

# 更新部署
sudo bash scripts/update-from-github.sh --domain your-domain.com
```

脚本会自动设置以下环境变量：
- `CORS_ORIGIN=https://your-domain.com,http://your-domain.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.com,http://your-domain.com`
- `SECURE_COOKIES=true`

### 2. 手动配置

如果需要手动配置，请在`backend/.env`文件中添加以下配置：

```env
# HTTPS cookie安全设置
SECURE_COOKIES=true

# CORS白名单
CORS_ORIGIN=https://your-domain.com,http://your-domain.com

# CSRF Origin白名单
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.com,http://your-domain.com

# 允许的主机
DJANGO_ALLOWED_HOSTS=your-domain.com,log.your-domain.com,localhost,127.0.0.1

# 日志查看器公网地址（可选）
LOG_VIEWER_PUBLIC_URL=https://log.your-domain.com/
```

### 3. 验证配置

运行测试脚本验证配置是否正确：

```bash
cd backend
python test_https_config.py
```

## 配置说明

### SECURE_COOKIES

- `true`: 启用HTTPS cookie安全设置（推荐用于HTTPS部署）
- `false`: 禁用HTTPS cookie安全设置（用于HTTP部署）

### CORS_ORIGIN

CORS白名单，多个域名用逗号分隔：
```
CORS_ORIGIN=https://domain1.com,https://domain2.com
```

### DJANGO_CSRF_TRUSTED_ORIGINS

CSRF Origin白名单，多个域名用逗号分隔：
```
DJANGO_CSRF_TRUSTED_ORIGINS=https://domain1.com,https://domain2.com
```

### DJANGO_ALLOWED_HOSTS

允许的主机名，多个主机用逗号分隔：
```
DJANGO_ALLOWED_HOSTS=domain.com,log.domain.com,localhost,127.0.0.1
```

## 常见问题

### 1. 部署后仍然出现"身份认证信息未提供"

**可能原因**：
- 环境变量未生效（需要重启服务）
- 浏览器缓存了旧的cookie
- 反向代理配置问题

**解决方案**：
1. 重启Django服务：
   ```bash
   sudo systemctl restart gipfel.service
   ```
2. 清除浏览器缓存和cookie
3. 检查反向代理配置，确保正确传递`X-Forwarded-Proto`头

### 2. HTTPS部署后无法登录

**可能原因**：
- `SECURE_COOKIES`设置为`true`，但客户端通过HTTP访问
- CSRF cookie无法正确传递

**解决方案**：
1. 确保客户端通过HTTPS访问
2. 检查反向代理配置，确保正确设置`proxy_set_header X-Forwarded-Proto $scheme`

### 3. CORS错误

**可能原因**：
- `CORS_ORIGIN`未正确配置
- 前端域名不在白名单中

**解决方案**：
1. 检查`CORS_ORIGIN`配置是否包含前端域名
2. 确保前端域名格式正确（包含协议，如`https://domain.com`）

## 技术细节

### Django HTTPS支持

Django通过`SECURE_PROXY_SSL_HEADER`设置支持反向代理的HTTPS：

```python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

这允许Django通过检查`X-Forwarded-Proto`头来判断请求是否为HTTPS。

### Cookie安全标记

- `Secure`: cookie只能通过HTTPS传输
- `HttpOnly`: cookie不能通过JavaScript访问
- `SameSite`: cookie的跨站发送策略

### CSRF保护

Django的CSRF保护机制：
1. 在cookie中设置`csrftoken`
2. 在表单或请求头中包含`X-CSRFToken`
3. 验证两者是否匹配

## 监控和调试

### 查看审计日志

```bash
# 查看最新的审计日志
tail -f backend/logs/gipfel.log | grep "身份认证信息未提供"
```

### 检查Django设置

```bash
cd backend
python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from django.conf import settings
print('SESSION_COOKIE_SECURE:', settings.SESSION_COOKIE_SECURE)
print('CSRF_COOKIE_SECURE:', settings.CSRF_COOKIE_SECURE)
print('CORS_ALLOWED_ORIGINS:', settings.CORS_ALLOWED_ORIGINS)
print('CSRF_TRUSTED_ORIGINS:', settings.CSRF_TRUSTED_ORIGINS)
"
```

### 检查环境变量

```bash
cd backend
grep -E "^(SECURE_COOKIES|CORS_ORIGIN|DJANGO_CSRF_TRUSTED_ORIGINS|DJANGO_ALLOWED_HOSTS)" .env
```

## 最佳实践

1. **始终使用HTTPS**：生产环境应始终使用HTTPS
2. **定期更新证书**：确保证书在有效期内
3. **监控审计日志**：定期检查审计日志，及时发现认证问题
4. **测试部署**：在测试环境验证配置后再部署到生产环境
5. **备份配置**：修改配置前备份`.env`文件

## 相关文件

- `backend/backend/settings.py`: Django主配置文件
- `backend/.env`: 环境变量配置文件
- `scripts/deploy-linux.sh`: 部署脚本
- `scripts/update-from-github.sh`: 更新脚本
- `backend/apps/common/exceptions.py`: 异常处理器
- `backend/apps/common/audit.py`: 审计日志模块