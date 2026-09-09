#!/usr/bin/env python3
"""测试优化后的做市商算法"""
import math

def clamp(v: float, lo: float, hi: float) -> float:
    """限幅辅助：把 v 截断到 [lo, hi]。"""
    return max(lo, min(hi, v))

def calculate_fundamental_score(pe, carbon, avg_carbon, happiness, total_shares):
    """基于根源数据计算股票基本面评分（-1到1之间）。"""
    score = 0.0
    weight_sum = 0.0
    
    # 1. PE评分：PE越低，估值越有吸引力
    if pe and pe > 0:
        pe_score = clamp((15 - pe) / 10.0, -1.0, 1.0)
        score += pe_score * 0.3
        weight_sum += 0.3
    
    # 2. 碳排评分：碳排越低越好
    if carbon is not None and avg_carbon and avg_carbon > 0:
        carbon_ratio = carbon / avg_carbon
        carbon_score = clamp((1.0 - carbon_ratio) * 2.0, -1.0, 1.0)
        score += carbon_score * 0.25
        weight_sum += 0.25
    
    # 3. 幸福度评分：幸福度越高越好
    if happiness is not None:
        happiness_score = clamp((happiness - 50) / 50.0, -1.0, 1.0)
        score += happiness_score * 0.25
        weight_sum += 0.25
    
    # 4. 股本规模评分：适中股本更受欢迎
    if total_shares and total_shares > 0:
        shares_billion = total_shares / 10000  # 转换为亿股
        if shares_billion < 1:
            shares_score = shares_billion - 1
        elif shares_billion > 10:
            shares_score = clamp((10 - shares_billion) / 10.0, -1.0, 0)
        else:
            shares_score = 0.2
        score += shares_score * 0.2
        weight_sum += 0.2
    
    # 归一化评分
    if weight_sum > 0:
        score = score / weight_sum
    
    return clamp(score, -1.0, 1.0)

def test_fundamental_scoring():
    """测试基本面评分算法"""
    print("测试做市商基本面评分算法")
    print("=" * 70)
    
    test_cases = [
        {
            "name": "优质股票（低PE、低碳排、高幸福度）",
            "pe": 8.0, "carbon": 50.0, "avg_carbon": 100.0, 
            "happiness": 80.0, "total_shares": 50000
        },
        {
            "name": "劣质股票（高PE、高碳排、低幸福度）",
            "pe": 25.0, "carbon": 150.0, "avg_carbon": 100.0, 
            "happiness": 20.0, "total_shares": 50000
        },
        {
            "name": "中性股票（各项指标中等）",
            "pe": 15.0, "carbon": 100.0, "avg_carbon": 100.0, 
            "happiness": 50.0, "total_shares": 50000
        },
        {
            "name": "小盘成长股（低PE、小股本）",
            "pe": 10.0, "carbon": 80.0, "avg_carbon": 100.0, 
            "happiness": 60.0, "total_shares": 5000
        },
        {
            "name": "大盘价值股（低PE、大股本）",
            "pe": 12.0, "carbon": 90.0, "avg_carbon": 100.0, 
            "happiness": 70.0, "total_shares": 200000
        },
    ]
    
    for case in test_cases:
        score = calculate_fundamental_score(
            case["pe"], case["carbon"], case["avg_carbon"], 
            case["happiness"], case["total_shares"]
        )
        
        print(f"\n{case['name']}:")
        print(f"  PE: {case['pe']}, 碳排: {case['carbon']}/{case['avg_carbon']}")
        print(f"  幸福度: {case['happiness']}, 股本: {case['total_shares']/10000:.1f}亿股")
        print(f"  基本面评分: {score:.3f}")
        
        # 解释评分含义
        if score > 0.2:
            print(f"  → 做市商倾向：推高价格（评分>{0.2}）")
        elif score < -0.2:
            print(f"  → 做市商倾向：压低价格（评分<{-0.2}）")
        else:
            print(f"  → 做市商倾向：中性（评分在{-0.2}~{0.2}之间）")
        
        # 显示自成交策略
        base_qty = 1000
        if score > 0.2:
            buy_qty = int(round(base_qty * (1 + score)))
            sell_qty = base_qty
            print(f"  → 自成交策略：买{buy_qty}股，卖{sell_qty}股（多买少卖）")
        elif score < -0.2:
            buy_qty = base_qty
            sell_qty = int(round(base_qty * (1 + abs(score))))
            print(f"  → 自成交策略：买{buy_qty}股，卖{sell_qty}股（少买多卖）")
        else:
            buy_qty = base_qty
            sell_qty = base_qty
            print(f"  → 自成交策略：买{buy_qty}股，卖{sell_qty}股（均衡）")
        
        print("-" * 50)

if __name__ == "__main__":
    test_fundamental_scoring()