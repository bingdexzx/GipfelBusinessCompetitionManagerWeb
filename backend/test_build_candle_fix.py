#!/usr/bin/env python
"""
测试build_candle函数的修复
"""
import os
import sys
from decimal import Decimal

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 设置Django环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

try:
    import django
    django.setup()
    
    from apps.stock.engine import build_candle
    
    print("测试build_candle函数的Decimal/float类型兼容性...")
    
    # 测试用例1：传入float类型
    print("\n测试用例1：传入float类型")
    try:
        candle = build_candle(10.0, 10.5, 1, None, 0.1)
        print("[OK] float类型测试通过")
        print(f"  open: {candle['open']}, close: {candle['close']}")
    except Exception as e:
        print(f"[ERROR] float类型测试失败: {e}")
    
    # 测试用例2：传入Decimal类型
    print("\n测试用例2：传入Decimal类型")
    try:
        candle = build_candle(Decimal('10.0'), Decimal('10.5'), 1, None, 0.1)
        print("[OK] Decimal类型测试通过")
        print(f"  open: {candle['open']}, close: {candle['close']}")
    except Exception as e:
        print(f"[ERROR] Decimal类型测试失败: {e}")
    
    # 测试用例3：混合类型（open为Decimal，close为float）
    print("\n测试用例3：混合类型（open为Decimal，close为float）")
    try:
        candle = build_candle(Decimal('10.0'), 10.5, 1, None, 0.1)
        print("[OK] 混合类型测试通过")
        print(f"  open: {candle['open']}, close: {candle['close']}")
    except Exception as e:
        print(f"[ERROR] 混合类型测试失败: {e}")
    
    # 测试用例4：混合类型（open为float，close为Decimal）
    print("\n测试用例4：混合类型（open为float，close为Decimal）")
    try:
        candle = build_candle(10.0, Decimal('10.5'), 1, None, 0.1)
        print("[OK] 混合类型测试通过")
        print(f"  open: {candle['open']}, close: {candle['close']}")
    except Exception as e:
        print(f"[ERROR] 混合类型测试失败: {e}")
    
    # 测试用例5：传入理论价（Decimal类型）
    print("\n测试用例5：传入理论价（Decimal类型）")
    try:
        candle = build_candle(Decimal('10.0'), Decimal('10.5'), 1, Decimal('10.2'), 0.1)
        print("[OK] 理论价Decimal类型测试通过")
        print(f"  open: {candle['open']}, close: {candle['close']}, theoretical: {candle.get('theoretical')}")
    except Exception as e:
        print(f"[ERROR] 理论价Decimal类型测试失败: {e}")
    
    print("\n=== 测试总结 ===")
    print("所有测试用例都已执行。")
    print("如果看到'[OK]'，说明修复有效。")
    print("如果看到'[ERROR]'，说明仍有问题需要修复。")
    
except Exception as e:
    print(f"[ERROR] 测试失败: {e}")
    import traceback
    traceback.print_exc()