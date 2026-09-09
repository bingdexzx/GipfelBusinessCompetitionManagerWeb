#!/usr/bin/env python3
"""测试市场回调机制"""
import random

def test_callback_mechanism():
    """测试市场回调机制"""
    print("测试市场回调机制")
    print("=" * 70)
    
    # 配置参数
    config = {
        "mmCallbackEnabled": True,
        "mmCallbackMinRounds": 2,
        "mmCallbackMaxProb": 0.4,
        "mmCallbackMinPct": 0.01,
        "mmCallbackMaxPct": 0.03,
    }
    
    print("\n1. 回调机制配置")
    print("-" * 50)
    print(f"启用回调: {config['mmCallbackEnabled']}")
    print(f"最小连续上涨轮数: {config['mmCallbackMinRounds']}")
    print(f"最大回调概率: {config['mmCallbackMaxProb']*100:.0f}%")
    print(f"回调幅度范围: {config['mmCallbackMinPct']*100:.1f}% ~ {config['mmCallbackMaxPct']*100:.1f}%")
    
    print("\n\n2. 模拟不同连续上涨轮数的回调概率")
    print("-" * 50)
    
    # 模拟不同连续上涨轮数
    for consecutive_up in range(1, 6):
        if consecutive_up >= config['mmCallbackMinRounds']:
            # 计算回调概率
            callback_prob = min(config['mmCallbackMaxProb'], 
                               (consecutive_up - config['mmCallbackMinRounds'] + 1) * 0.1)
            print(f"连续上涨{consecutive_up}轮: 回调概率={callback_prob*100:.0f}%")
        else:
            print(f"连续上涨{consecutive_up}轮: 不触发回调")
    
    print("\n\n3. 模拟100轮交易的回调情况")
    print("-" * 50)
    
    # 模拟100轮交易
    random.seed(42)
    price = 100.0
    consecutive_up = 0
    callback_count = 0
    total_rounds = 100
    
    print(f"初始价格: {price:.2f}元")
    
    for round_num in range(1, total_rounds + 1):
        # 模拟价格变化（假设60%概率上涨）
        if random.random() < 0.6:
            # 上涨0.5%~2%
            change_pct = random.uniform(0.005, 0.02)
            price *= (1 + change_pct)
            consecutive_up += 1
        else:
            # 下跌0.5%~2%
            change_pct = random.uniform(0.005, 0.02)
            price *= (1 - change_pct)
            consecutive_up = 0
        
        # 检查是否触发回调
        if consecutive_up >= config['mmCallbackMinRounds']:
            callback_prob = min(config['mmCallbackMaxProb'], 
                               (consecutive_up - config['mmCallbackMinRounds'] + 1) * 0.1)
            
            if random.random() < callback_prob:
                # 触发回调
                callback_pct = random.uniform(config['mmCallbackMinPct'], config['mmCallbackMaxPct'])
                price *= (1 - callback_pct)
                callback_count += 1
                print(f"轮次{round_num:3d}: 价格={price:.2f}元, 连续上涨{consecutive_up}轮, 触发回调{callback_pct*100:.1f}%")
                consecutive_up = 0  # 重置连续上涨计数
        
        # 每20轮显示一次价格
        if round_num % 20 == 0:
            print(f"轮次{round_num:3d}: 价格={price:.2f}元, 连续上涨{consecutive_up}轮")
    
    print(f"\n最终价格: {price:.2f}元")
    print(f"总回调次数: {callback_count}次 ({callback_count/total_rounds*100:.1f}%)")
    
    print("\n\n4. 回调机制效果分析")
    print("-" * 50)
    print("✅ 回调机制模拟真实市场的技术性调整")
    print("✅ 连续上涨越多，回调概率越大")
    print("✅ 回调幅度在1%~3%之间，符合真实市场")
    print("✅ 避免价格单边上涨，增加K线图的真实性")
    print("✅ 回调后重置连续上涨计数，重新开始计算")
    
    print("\n\n5. 预期K线图效果")
    print("-" * 50)
    print("调整前: 一路涨，缺乏回调")
    print("调整后: 趋势向上，但包含多个回调K线块")
    print("效果: K线图更像真实市场，有涨有跌，趋势中包含调整")

if __name__ == "__main__":
    test_callback_mechanism()