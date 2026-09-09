#!/usr/bin/env python3
"""测试市场自然波动机制"""
import random

def test_natural_fluctuation():
    """测试市场自然波动机制"""
    print("测试市场自然波动机制")
    print("=" * 70)
    
    # 模拟100轮交易
    random.seed(42)
    price = 100.0
    recent_changes = []
    total_rounds = 100
    callback_count = 0
    sentiment_count = 0
    
    print(f"初始价格: {price:.2f}元")
    print("\n模拟100轮交易（每轮显示关键事件）:")
    print("-" * 70)
    
    for round_num in range(1, total_rounds + 1):
        # 模拟基础价格变化（55%概率上涨）
        if random.random() < 0.55:
            # 上涨0.3%~1.5%
            change_pct = random.uniform(0.003, 0.015)
            price *= (1 + change_pct)
            recent_changes.append(change_pct * 100)
        else:
            # 下跌0.3%~1.5%
            change_pct = random.uniform(0.003, 0.015)
            price *= (1 - change_pct)
            recent_changes.append(-change_pct * 100)
        
        # 保持最近5轮的变化记录
        if len(recent_changes) > 5:
            recent_changes = recent_changes[-5:]
        
        # 计算技术指标
        avg_change = sum(recent_changes) / len(recent_changes)
        
        # 计算连续涨跌轮数
        consecutive_up = 0
        consecutive_down = 0
        for change in reversed(recent_changes):
            if change > 0:
                consecutive_up += 1
                consecutive_down = 0
            elif change < 0:
                consecutive_down += 1
                consecutive_up = 0
            else:
                break
        
        # 基于多种因素计算回调概率
        base_prob = 0.05  # 基础回调概率5%
        
        # 因素1：连续上涨轮数（非线性）
        if consecutive_up >= 3:
            up_factor = min(0.2, (consecutive_up - 2) * 0.05)
            base_prob += up_factor
        
        # 因素2：近期平均涨幅（涨幅越大，回调概率越大）
        if avg_change > 1.0:  # 平均涨幅超过1%
            change_factor = min(0.15, (avg_change - 1.0) * 0.05)
            base_prob += change_factor
        
        # 因素3：随机市场情绪（10%概率出现市场情绪变化）
        if random.random() < 0.1:
            # 市场情绪变化：可能大涨也可能大跌
            sentiment = random.choice([-1, 1])
            sentiment_pct = random.uniform(0.005, 0.02)  # 0.5%~2%
            price *= (1 + sentiment * sentiment_pct)
            sentiment_count += 1
            print(f"轮次{round_num:3d}: 价格={price:.2f}元, 市场情绪变化{'上涨' if sentiment > 0 else '下跌'}{sentiment_pct*100:.1f}%")
        
        # 因素4：技术性回调（基于概率）
        if random.random() < base_prob:
            # 回调幅度：基于近期涨幅
            if avg_change > 1.5:
                # 大涨后可能大跌
                callback_pct = random.uniform(0.015, 0.04)  # 1.5%~4%
            elif avg_change > 1.0:
                # 中等涨幅后回调
                callback_pct = random.uniform(0.01, 0.025)  # 1%~2.5%
            else:
                # 小幅回调
                callback_pct = random.uniform(0.005, 0.015)  # 0.5%~1.5%
            
            price *= (1 - callback_pct)
            callback_count += 1
            print(f"轮次{round_num:3d}: 价格={price:.2f}元, 技术性回调{callback_pct*100:.1f}%")
        
        # 每20轮显示一次价格
        if round_num % 20 == 0:
            print(f"轮次{round_num:3d}: 价格={price:.2f}元, 近期平均变化{avg_change:.2f}%")
    
    print(f"\n最终价格: {price:.2f}元")
    print(f"总回调次数: {callback_count}次 ({callback_count/total_rounds*100:.1f}%)")
    print(f"市场情绪变化: {sentiment_count}次 ({sentiment_count/total_rounds*100:.1f}%)")
    
    print("\n\n自然波动机制特点:")
    print("-" * 70)
    print("1. 基础回调概率低（5%），不会每次都回调")
    print("2. 连续上涨3轮以上才开始增加回调概率")
    print("3. 近期涨幅越大，回调概率越大")
    print("4. 随机市场情绪变化（10%概率）")
    print("5. 回调幅度基于近期涨幅，涨幅越大回调可能越大")
    print("6. 不会出现明显的'先涨后跌'模式")
    print("7. 回调更自然，符合真实市场行为")
    
    print("\n\n预期效果:")
    print("-" * 70)
    print("✅ 不会出现明显的'先涨后跌'模式")
    print("✅ 回调更随机，更符合真实市场")
    print("✅ 趋势保持向上，但波动更自然")
    print("✅ K线图看起来更像真实市场")

if __name__ == "__main__":
    test_natural_fluctuation()