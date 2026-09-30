#!/usr/bin/env python
"""
简单的配置检查脚本
"""
import os

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

print("=== 配置检查 ===")
print()

# 检查关键配置
configs = [
    ("SECURE_COOKIES", "HTTPS cookie安全设置"),
    ("CORS_ORIGIN", "CORS白名单"),
    ("DJANGO_CSRF_TRUSTED_ORIGINS", "CSRF Origin白名单"),
    ("DJANGO_ALLOWED_HOSTS", "允许的主机"),
]

for key, desc in configs:
    value = os.environ.get(key, "").strip()
    if value:
        print(f"[OK] {desc}: {value}")
    else:
        print(f"[WARN] {desc}: 未配置")

print()
print("=== 建议 ===")
print("如果要启用HTTPS支持，请在backend/.env文件中添加：")
print("SECURE_COOKIES=true")
print("CORS_ORIGIN=https://your-domain.com,http://your-domain.com")
print("DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.com,http://your-domain.com")
print("DJANGO_ALLOWED_HOSTS=your-domain.com,log.your-domain.com,localhost,127.0.0.1")