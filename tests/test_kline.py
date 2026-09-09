#!/usr/bin/env python3
"""测试K线影线长度算法（基于真实订单）"""
import math

def candle_noise(seed_a: float, seed_b: float) -> float:
    """确定性伪随机：由两个种子派生 [0,1) 的伪随机数（正弦哈希，可复现）。"""
    x = math.sin(float(seed_a) * 127.1 + float(seed_b) * 311.7) * 43758.5453
    return x - math.floor(x)

def test_wick_length():
    """测试不同场景下的影线长度"""
    print("测试K线影线长度算法（基于真实订单）")
    print("=" * 70)
    
    # 测试场景1：有真实成交
    print("\n场景1：有真实成交订单")
    print("-" * 40)
    test_cases_with_trades = [
        {"open": 100.0, "close": 102.0, "round": 1, "trade_high": 103.0, "trade_low": 99.0},
        {"open": 50.0, "close": 48.0, "round": 2, "trade_high": 52.0, "trade_low": 47.0},
        {"open": 200.0, "close": 200.0, "round": 3, "trade_high": 201.0, "trade_low": 199.0},
    ]
    
    for case in test_cases_with_trades:
        open_ = case["open"]
        close = case["close"]
        round_ = case["round"]
        trade_high = case["trade_high"]
        trade_low = case["trade_low"]
        
        # 计算基于真实成交的影线
        trade_range = trade_high - trade_low
        base_wick = trade_range * (0.3 + 0.4 * candle_noise(round_, open_))
        
        random_factor_a = 0.6 + 0.8 * candle_noise(round_, open_)
        random_factor_b = 0.6 + 0.8 * candle_noise(round_ * 3 + 7, open_)
        
        up_wick = base_wick * random_factor_a
        down_wick = base_wick * random_factor_b
        
        print(f"股价: {open_:.2f}元, 收盘: {close:.2f}元")
        print(f"  成交价范围: {trade_low:.2f} ~ {trade_high:.2f} (幅度: {trade_range:.2f}元)")
        print(f"  基础影线长度: {base_wick:.3f}元")
        print(f"  上影线长度: {up_wick:.3f}元 ({up_wick/open_*100:.3f}%)")
        print(f"  下影线长度: {down_wick:.3f}元 ({down_wick/open_*100:.3f}%)")
        print("-" * 40)
    
    # 测试场景2：无成交但有理论价
    print("\n场景2：无成交但有理论价")
    print("-" * 40)
    test_cases_with_theory = [
        {"open": 100.0, "close": 100.0, "round": 4, "theoretical": 105.0},
        {"open": 80.0, "close": 80.0, "round": 5, "theoretical": 75.0},
    ]
    
    for case in test_cases_with_theory:
        open_ = case["open"]
        close = case["close"]
        round_ = case["round"]
        theoretical = case["theoretical"]
        
        # 计算基于理论价的影线
        theory_diff = abs(theoretical - close)
        base_wick = theory_diff * (0.5 + 0.5 * candle_noise(round_, open_))
        
        random_factor_a = 0.6 + 0.8 * candle_noise(round_, open_)
        random_factor_b = 0.6 + 0.8 * candle_noise(round_ * 3 + 7, open_)
        
        up_wick = base_wick * random_factor_a
        down_wick = base_wick * random_factor_b
        
        print(f"股价: {open_:.2f}元, 收盘: {close:.2f}元, 理论价: {theoretical:.2f}元")
        print(f"  理论价差异: {theory_diff:.2f}元")
        print(f"  基础影线长度: {base_wick:.3f}元")
        print(f"  上影线长度: {up_wick:.3f}元 ({up_wick/open_*100:.3f}%)")
        print(f"  下影线长度: {down_wick:.3f}元 ({down_wick/open_*100:.3f}%)")
        print("-" * 40)
    
    # 测试场景3：无成交无理论价（平盘）
    print("\n场景3：无成交无理论价（平盘）")
    print("-" * 40)
    test_cases_flat = [
        {"open": 100.0, "close": 100.0, "round": 6},
        {"open": 50.0, "close": 50.0, "round": 7},
    ]
    
    for case in test_cases_flat:
        open_ = case["open"]
        close = case["close"]
        round_ = case["round"]
        
        # 计算基于股价百分比的影线
        change_pct_abs = abs(close - open_) / open_ if open_ > 0 else 0
        base_wick_pct = 0.003 + min(0.007, change_pct_abs * 0.3)
        base_wick = open_ * base_wick_pct
        
        random_factor_a = 0.6 + 0.8 * candle_noise(round_, open_)
        random_factor_b = 0.6 + 0.8 * candle_noise(round_ * 3 + 7, open_)
        
        up_wick = base_wick * random_factor_a
        down_wick = base_wick * random_factor_b
        
        print(f"股价: {open_:.2f}元, 收盘: {close:.2f}元 (平盘)")
        print(f"  基础影线比例: {base_wick_pct*100:.3f}%")
        print(f"  上影线长度: {up_wick:.3f}元 ({up_wick/open_*100:.3f}%)")
        print(f"  下影线长度: {down_wick:.3f}元 ({down_wick/open_*100:.3f}%)")
        print("-" * 40)

if __name__ == "__main__":
    test_wick_length()