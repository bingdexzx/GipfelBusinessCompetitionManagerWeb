#!/usr/bin/env python3
"""测试改进后的做市商算法"""
import random
import math

def clamp(v: float, lo: float, hi: float) -> float:
    """限幅辅助：把 v 截断到 [lo, hi]。"""
    return max(lo, min(hi, v))

def calculate_fundamental_score(pe, carbon, avg_carbon, happiness, total_shares):
    """基于根源数据计算股票基本面评分（-0.5到0.5之间）"""
    score = 0.0
    weight_sum = 0.0
    
    # 1. PE评分：引入估值约束
    if pe and pe > 0:
        if pe < 8:
            pe_score = 0.0  # PE过低，可能是价值陷阱
        elif pe > 18:
            pe_score = clamp((18 - pe) / 10.0, -1.0, 0.0)  # PE过高，减分
        else:
            pe_score = clamp((15 - pe) / 10.0, -0.5, 0.5)  # 合理区间
        score += pe_score * 0.25
        weight_sum += 0.25
    
    # 2. 碳排评分：只有明显优于行业平均才加分
    if carbon is not None and avg_carbon and avg_carbon > 0:
        carbon_ratio = carbon / avg_carbon
        if carbon_ratio < 0.8:
            carbon_score = clamp((0.8 - carbon_ratio) * 2.0, 0.0, 0.5)
        elif carbon_ratio > 1.2:
            carbon_score = clamp((1.0 - carbon_ratio) * 2.0, -0.5, 0.0)
        else:
            carbon_score = 0.0
        score += carbon_score * 0.2
        weight_sum += 0.2
    
    # 3. 幸福度评分：边际效应递减
    if happiness is not None:
        if happiness > 70:
            happiness_score = clamp((happiness - 50) / 100.0, 0.0, 0.3)
        else:
            happiness_score = clamp((happiness - 50) / 50.0, -0.5, 0.2)
        score += happiness_score * 0.2
        weight_sum += 0.2
    
    # 4. 股本规模评分
    if total_shares and total_shares > 0:
        shares_billion = total_shares / 10000
        if shares_billion < 1:
            shares_score = (shares_billion - 1) * 0.5
        elif shares_billion > 10:
            shares_score = clamp((10 - shares_billion) / 20.0, -0.3, 0)
        else:
            shares_score = 0.1
        score += shares_score * 0.15
        weight_sum += 0.15
    
    # 5. 随机市场情绪因子
    market_sentiment = random.uniform(-0.2, 0.2)
    score += market_sentiment * 0.2
    weight_sum += 0.2
    
    # 归一化评分
    if weight_sum > 0:
        score = score / weight_sum
    
    return clamp(score, -0.5, 0.5)

def test_improved_algorithm():
    """测试改进后的算法"""
    print("测试改进后的做市商算法")
    print("=" * 70)
    
    test_cases = [
        {
            "name": "优质股票（PE=8, 碳排低, 幸福度高）",
            "pe": 8.0, "carbon": 50.0, "avg_carbon": 100.0, 
            "happiness": 80.0, "total_shares": 50000
        },
        {
            "name": "劣质股票（PE=25, 碳排高, 幸福度低）",
            "pe": 25.0, "carbon": 150.0, "avg_carbon": 100.0, 
            "happiness": 20.0, "total_shares": 50000
        },
        {
            "name": "中性股票（各项指标中等）",
            "pe": 15.0, "carbon": 100.0, "avg_carbon": 100.0, 
            "happiness": 50.0, "total_shares": 50000
        },
        {
            "name": "价值陷阱（PE过低=5）",
            "pe": 5.0, "carbon": 80.0, "avg_carbon": 100.0, 
            "happiness": 60.0, "total_shares": 50000
        },
        {
            "name": "高估股票（PE过高=30）",
            "pe": 30.0, "carbon": 120.0, "avg_carbon": 100.0, 
            "happiness": 40.0, "total_shares": 50000
        },
    ]
    
    print("\n1. 基本面评分测试（改进后）")
    print("-" * 50)
    
    for case in test_cases:
        score = calculate_fundamental_score(
            case["pe"], case["carbon"], case["avg_carbon"], 
            case["happiness"], case["total_shares"]
        )
        
        print(f"\n{case['name']}:")
        print(f"  基本面评分: {score:.3f} (范围: -0.5~0.5)")
        
        # 显示影响
        if score > 0.1:
            print(f"  → 轻微推高价格倾向")
        elif score < -0.1:
            print(f"  → 轻微压低价格倾向")
        else:
            print(f"  → 中性倾向")
    
    print("\n\n2. 随机事件测试")
    print("-" * 50)
    
    # 模拟随机事件
    random.seed(42)  # 固定种子便于复现
    bad_news_count = 0
    good_news_count = 0
    total_rounds = 100
    
    for i in range(total_rounds):
        if random.random() < 0.05:  # 5%利空概率
            bad_news_count += 1
        elif random.random() < 0.03:  # 3%利好概率
            good_news_count += 1
    
    print(f"模拟{total_rounds}轮交易:")
    print(f"  利空事件: {bad_news_count}次 ({bad_news_count/total_rounds*100:.1f}%)")
    print(f"  利好事件: {good_news_count}次 ({good_news_count/total_rounds*100:.1f}%)")
    print(f"  中性轮次: {total_rounds - bad_news_count - good_news_count}次")
    
    print("\n\n3. 估值回归测试")
    print("-" * 50)
    
    # 模拟估值回归
    test_deviations = [0.1, 0.2, 0.3, 0.5, -0.3, -0.5]
    regression_threshold = 0.2
    regression_strength = 0.5
    
    for deviation in test_deviations:
        if abs(deviation) > regression_threshold:
            regression_skew = -deviation * 0.02 * regression_strength  # 假设skew_pct=0.02
            print(f"价格偏离{deviation*100:+.0f}%: 回归力量{regression_skew*100:+.3f}%")
        else:
            print(f"价格偏离{deviation*100:+.0f}%: 无回归力量")

if __name__ == "__main__":
    test_improved_algorithm()