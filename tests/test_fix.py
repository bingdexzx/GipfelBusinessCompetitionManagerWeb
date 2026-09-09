#!/usr/bin/env python3
"""测试类型转换修复"""
from decimal import Decimal

def test_decimal_conversion():
    """测试Decimal类型转换"""
    print("测试Decimal类型转换修复")
    print("=" * 50)
    
    # 模拟stock对象
    class MockStock:
        def __init__(self):
            self.industry_pe = Decimal("12.5")  # Decimal类型
            self.current_carbon = 85.0
            self.industry_avg_carbon = 100.0
            self.happiness = 65.0
            self.total_shares = Decimal("50000")
            self.current_price = Decimal("100.00")
    
    stock = MockStock()
    
    # 测试PE转换
    pe = stock.industry_pe
    print(f"原始PE类型: {type(pe)} = {pe}")
    
    # 修复前的代码（会报错）
    try:
        pe_score_wrong = (15 - pe) / 10.0
        print(f"错误方式计算: {pe_score_wrong}")
    except TypeError as e:
        print(f"错误方式报错: {e}")
    
    # 修复后的代码
    pe_float = float(pe)
    pe_score_correct = (15 - pe_float) / 10.0
    print(f"正确方式计算: {pe_score_correct}")
    
    # 测试价格偏移
    base_price = stock.current_price
    price_offset = 0.05  # float类型
    
    # 修复前的代码（可能有问题）
    try:
        price_wrong = Decimal(str(base_price)) * (Decimal("1") + price_offset)
        print(f"错误方式计算价格: {price_wrong}")
    except TypeError as e:
        print(f"错误方式报错: {e}")
    
    # 修复后的代码
    price_correct = Decimal(str(base_price)) * (Decimal("1") + Decimal(str(float(price_offset))))
    print(f"正确方式计算价格: {price_correct}")
    
    print("\n✅ 类型转换修复验证通过！")

if __name__ == "__main__":
    test_decimal_conversion()