#!/usr/bin/env python
"""
HTTPS部署诊断脚本
用于检查和诊断HTTPS部署中的认证问题
"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

def check_env_file():
    """检查.env文件配置"""
    print("=== 检查.env文件配置 ===")
    
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_file):
        print("[ERROR] .env文件不存在")
        return False
    
    print("[OK] .env文件存在")
    
    # 读取.env文件
    with open(env_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查关键配置
    checks = [
        ("SECURE_COOKIES", "HTTPS cookie安全设置"),
        ("CORS_ORIGIN", "CORS白名单"),
        ("DJANGO_CSRF_TRUSTED_ORIGINS", "CSRF Origin白名单"),
        ("DJANGO_ALLOWED_HOSTS", "允许的主机"),
    ]
    
    all_ok = True
    for key, desc in checks:
        if key in content:
            # 提取值
            for line in content.split('\n'):
                if line.startswith(f'{key}=') and not line.startswith('#'):
                    value = line.split('=', 1)[1].strip()
                    if value and value != '""':
                        print(f"[OK] {desc}: {value}")
                    else:
                        print(f"[ERROR] {desc}: 未配置或为空")
                        all_ok = False
                    break
        else:
            print(f"[ERROR] {desc}: 未配置")
            all_ok = False
    
    return all_ok

def check_django_settings():
    """检查Django设置"""
    print("\n=== 检查Django设置 ===")
    
    try:
        # 设置Django环境
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
        import django
        django.setup()
        
        from django.conf import settings
        
        # 检查关键设置
        checks = [
            ("SESSION_COOKIE_SECURE", "Session Cookie Secure"),
            ("CSRF_COOKIE_SECURE", "CSRF Cookie Secure"),
            ("SECURE_PROXY_SSL_HEADER", "Secure Proxy SSL Header"),
        ]
        
        for setting, desc in checks:
            value = getattr(settings, setting, None)
            if value:
                print(f"[OK] {desc}: {value}")
            else:
                print(f"[ERROR] {desc}: 未设置")
        
        # 检查CORS设置
        if hasattr(settings, 'CORS_ALLOWED_ORIGINS'):
            if settings.CORS_ALLOWED_ORIGINS:
                print(f"[OK] CORS允许的来源: {settings.CORS_ALLOWED_ORIGINS}")
            else:
                print("[ERROR] CORS允许的来源: 未配置")
        
        # 检查CSRF设置
        if hasattr(settings, 'CSRF_TRUSTED_ORIGINS'):
            if settings.CSRF_TRUSTED_ORIGINS:
                print(f"[OK] CSRF受信来源: {settings.CSRF_TRUSTED_ORIGINS}")
            else:
                print("[ERROR] CSRF受信来源: 未配置")
        
        # 检查ALLOWED_HOSTS
        if hasattr(settings, 'ALLOWED_HOSTS'):
            if settings.ALLOWED_HOSTS:
                print(f"[OK] 允许的主机: {settings.ALLOWED_HOSTS}")
            else:
                print("[ERROR] 允许的主机: 未配置")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Django设置加载失败: {e}")
        return False

def check_nginx_config():
    """检查Nginx配置（如果存在）"""
    print("\n=== 检查Nginx配置 ===")
    
    nginx_conf = os.path.join(os.path.dirname(__file__), '..', 'deploy', 'nginx-gipfel.conf')
    if not os.path.exists(nginx_conf):
        print("[WARN] Nginx配置文件不存在（可能未使用Nginx部署）")
        return True
    
    print("[OK] Nginx配置文件存在")
    
    with open(nginx_conf, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查关键配置
    checks = [
        ("proxy_set_header X-Forwarded-Proto", "X-Forwarded-Proto头设置"),
        ("proxy_set_header X-Forwarded-Host", "X-Forwarded-Host头设置"),
        ("proxy_set_header Host", "Host头设置"),
    ]
    
    for pattern, desc in checks:
        if pattern in content:
            print(f"[OK] {desc}")
        else:
            print(f"[ERROR] {desc}缺失")
    
    return True

def check_frontend_config():
    """检查前端配置"""
    print("\n=== 检查前端配置 ===")
    
    # 检查API请求配置
    request_file = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'src', 'api', 'request.ts')
    if os.path.exists(request_file):
        print("[OK] API请求配置文件存在")
        
        with open(request_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查token处理
        if 'Authorization' in content:
            print("[OK] Authorization头设置")
        else:
            print("[ERROR] Authorization头设置缺失")
    else:
        print("[ERROR] API请求配置文件不存在")
    
    return True

def main():
    """主函数"""
    print("HTTPS部署诊断工具")
    print("=" * 50)
    
    # 检查.env文件
    env_ok = check_env_file()
    
    # 检查Django设置
    django_ok = check_django_settings()
    
    # 检查Nginx配置
    nginx_ok = check_nginx_config()
    
    # 检查前端配置
    frontend_ok = check_frontend_config()
    
    print("\n" + "=" * 50)
    print("诊断结果")
    print("=" * 50)
    
    if all([env_ok, django_ok, nginx_ok, frontend_ok]):
        print("[OK] 所有检查通过，HTTPS配置应该正常工作")
        print("\n如果仍然出现'身份认证信息未提供'错误，请：")
        print("1. 重启Django服务: sudo systemctl restart gipfel.service")
        print("2. 清除浏览器缓存和cookie")
        print("3. 检查反向代理配置是否正确")
    else:
        print("[ERROR] 存在配置问题，请根据上述提示进行修复")
        print("\n建议：")
        print("1. 运行部署脚本重新配置: sudo bash scripts/deploy-linux.sh --domain your-domain.com --with-nginx --origin-cert")
        print("2. 或手动更新.env文件配置")

if __name__ == "__main__":
    main()