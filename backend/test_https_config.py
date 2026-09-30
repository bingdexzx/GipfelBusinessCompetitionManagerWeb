#!/usr/bin/env python
"""
测试HTTPS配置是否正确
"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# 测试SECURE_COOKIES环境变量
secure_cookies = os.environ.get("SECURE_COOKIES", "").strip().lower()
print(f"SECURE_COOKIES环境变量: {secure_cookies}")

# 测试CORS配置
cors_origin = os.environ.get("CORS_ORIGIN", "").strip()
print(f"CORS_ORIGIN环境变量: {cors_origin}")

# 测试CSRF配置
csrf_trusted_origins = os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").strip()
print(f"DJANGO_CSRF_TRUSTED_ORIGINS环境变量: {csrf_trusted_origins}")

# 测试ALLOWED_HOSTS配置
allowed_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "").strip()
print(f"DJANGO_ALLOWED_HOSTS环境变量: {allowed_hosts}")

# 测试LOG_VIEWER_PUBLIC_URL配置
log_viewer_url = os.environ.get("LOG_VIEWER_PUBLIC_URL", "").strip()
print(f"LOG_VIEWER_PUBLIC_URL环境变量: {log_viewer_url}")

# 验证配置
if secure_cookies == "true":
    print("✓ HTTPS cookie安全设置已启用")
else:
    print("✗ HTTPS cookie安全设置未启用")

if cors_origin:
    print("✓ CORS白名单已配置")
else:
    print("✗ CORS白名单未配置")

if csrf_trusted_origins:
    print("✓ CSRF Origin白名单已配置")
else:
    print("✗ CSRF Origin白名单未配置")

if allowed_hosts:
    print("✓ ALLOWED_HOSTS已配置")
else:
    print("✗ ALLOWED_HOSTS未配置")

# 模拟Django设置加载
print("\n模拟Django设置加载...")
try:
    # 设置Django环境
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
    import django
    django.setup()
    
    from django.conf import settings
    print(f"SESSION_COOKIE_SECURE: {settings.SESSION_COOKIE_SECURE}")
    print(f"CSRF_COOKIE_SECURE: {settings.CSRF_COOKIE_SECURE}")
    print(f"CORS_ALLOWED_ORIGINS: {settings.CORS_ALLOWED_ORIGINS}")
    print(f"CSRF_TRUSTED_ORIGINS: {settings.CSRF_TRUSTED_ORIGINS}")
    print(f"ALLOWED_HOSTS: {settings.ALLOWED_HOSTS}")
    
    if settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE:
        print("✓ Django已正确配置HTTPS cookie安全设置")
    else:
        print("✗ Django未正确配置HTTPS cookie安全设置")
        
except Exception as e:
    print(f"✗ Django设置加载失败: {e}")