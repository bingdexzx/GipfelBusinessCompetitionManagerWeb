#!/usr/bin/env python
"""
测试股票创建修复
"""
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

try:
    import django
    django.setup()
    
    from apps.stock.serializers import StockSerializer
    
    # 测试数据（使用一个假设存在的比赛ID）
    # 注意：在实际测试中，需要确保存在ID为1的比赛
    test_data = {
        'code': 'TEST001',
        'name': '测试股票',
        'totalShares': 1000000,
        'initNetProfit': 100000,
        'currentCarbon': 50.0,
        'industryAvgCarbon': 60.0,
        'happiness': 80.0,
        'competitionId': 1,  # 假设存在ID为1的比赛
    }
    
    print("测试StockSerializer字段验证...")
    
    # 测试serializer
    serializer = StockSerializer(data=test_data)
    
    # 检查serializer是否能正确验证code字段
    # 注意：由于competitionId可能不存在，验证可能会失败
    # 但我们主要关心code字段是否被正确处理
    
    # 手动检查code字段
    print(f"测试数据中的code字段: {test_data.get('code')}")
    
    # 检查serializer的字段定义
    print(f"StockSerializer中code字段是否为read_only: {serializer.fields['code'].read_only}")
    
    # 尝试验证（可能会因为competitionId不存在而失败）
    try:
        if serializer.is_valid():
            print("[OK] serializer验证通过")
            print(f"validated_data包含code字段: {'code' in serializer.validated_data}")
            if 'code' in serializer.validated_data:
                print(f"code字段值: {serializer.validated_data['code']}")
            else:
                print("[ERROR] code字段未包含在validated_data中")
        else:
            print("[WARN] serializer验证失败（可能是因为competitionId不存在）")
            print(f"错误信息: {serializer.errors}")
            # 即使验证失败，我们也应该检查code字段是否被正确处理
            print("注意：即使验证失败，code字段也不应该导致KeyError")
    except Exception as e:
        print(f"[ERROR] 验证过程中出现异常: {e}")
        import traceback
        traceback.print_exc()
        
except Exception as e:
    print(f"[ERROR] 测试失败: {e}")
    import traceback
    traceback.print_exc()