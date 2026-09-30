# HTTPS部署问题解决方案

## 问题描述

审计日志提示"身份认证信息未提供"的问题，主要原因是HTTPS部署环境下CSRF cookie的安全设置不完整。

## 解决方案

### 1. 使用部署脚本（推荐）

#### 新部署
```bash
sudo bash scripts/deploy-linux.sh --domain your-domain.com --with-nginx --origin-cert
```

#### 更新部署
```bash
sudo bash scripts/update-from-github.sh --domain your-domain.com
```

### 2. 手动配置

如果无法使用部署脚本，可以手动配置：

1. 编辑 `backend/.env` 文件，添加以下配置：
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

2. 重启Django服务：
```bash
sudo systemctl restart gipfel.service
```

### 3. 验证配置

#### 运行诊断脚本
```bash
cd backend
python diagnose_https.py
```

#### 运行测试脚本
```bash
cd backend
python test_https_config.py
```

#### 检查环境变量
```bash
cd backend
grep -E "^(SECURE_COOKIES|CORS_ORIGIN|DJANGO_CSRF_TRUSTED_ORIGINS|DJANGO_ALLOWED_HOSTS)" .env
```

#### 检查Django设置
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

## 常见问题

### Q1: 部署后仍然出现"身份认证信息未提供"

**A1:** 可能原因和解决方案：
1. **环境变量未生效**：重启Django服务
   ```bash
   sudo systemctl restart gipfel.service
   ```
2. **浏览器缓存问题**：清除浏览器缓存和cookie
3. **反向代理配置问题**：检查Nginx配置，确保正确传递`X-Forwarded-Proto`头

### Q2: HTTPS部署后无法登录

**A2:** 可能原因和解决方案：
1. **SECURE_COOKIES设置问题**：确保客户端通过HTTPS访问
2. **CSRF cookie问题**：检查反向代理配置

### Q3: CORS错误

**A3:** 可能原因和解决方案：
1. **CORS_ORIGIN配置问题**：检查是否包含前端域名
2. **域名格式问题**：确保包含协议（如`https://domain.com`）

## 技术细节

### Django HTTPS支持

Django通过`SECURE_PROXY_SSL_HEADER`设置支持反向代理的HTTPS：
```python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

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
tail -f backend/logs/gipfel.log | grep "身份认证信息未提供"
```

### 查看Nginx日志
```bash
tail -f /var/log/nginx/gipfel.access.log
tail -f /var/log/nginx/gipfel.error.log
```

### 检查系统服务状态
```bash
sudo systemctl status gipfel.service
sudo systemctl status nginx.service
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
- `backend/diagnose_https.py`: HTTPS部署诊断脚本
- `backend/test_https_config.py`: HTTPS配置测试脚本

## 联系支持

如果问题仍然存在，请提供以下信息：
1. 诊断脚本输出结果
2. Django服务日志
3. Nginx日志
4. 浏览器开发者工具网络请求详情