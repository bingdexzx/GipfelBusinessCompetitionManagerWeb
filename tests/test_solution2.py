#!/usr/bin/env python3
"""测试方案二：绝对评分兜底机制"""
import random

def clamp(v: float, lo: float, hi: float) -> float:
    """限幅辅助：把 v 截断到 [lo, hi]。"""
    return max(lo, min(hi, v))

def calculate_raw_fundamental_score(pe, carbon, avg_carbon, happiness, total_shares):
    """计算股票的原始基本面评分（用于相对排名）"""
    score = 50.0  # 基础分50
    
    # 1. PE评分：PE越低，估值越有吸引力
    if pe and pe > 0:
        if pe <= 10:
            score += 20  # 低PE加分
        elif pe <= 15:
            score += 10  # 合理PE加分
        elif pe <= 20:
            score += 0   # 中性
        else:
            score -= 10  # 高PE减分
    
    # 2. 碳排评分：碳排越低越好
    if carbon is not None and avg_carbon and avg_carbon > 0:
        carbon_ratio = carbon / avg_carbon
        if carbon_ratio < 0.7:
            score += 15  # 碳排明显优于行业平均
        elif carbon_ratio < 0.9:
            score += 5   # 碳排略优于行业平均
        elif carbon_ratio > 1.3:
            score -= 15  # 碳排明显高于行业平均
        elif carbon_ratio > 1.1:
            score -= 5   # 碳排略高于行业平均
    
    # 3. 幸福度评分：幸福度越高越好
    if happiness is not None:
        if happiness >= 80:
            score += 15  # 高幸福度
        elif happiness >= 60:
            score += 5   # 中等幸福度
        elif happiness < 40:
            score -= 10  # 低幸福度
    
    # 4. 股本规模评分：适中股本更受欢迎
    if total_shares and total_shares > 0:
        shares_billion = total_shares / 10000
        if 2 <= shares_billion <= 8:
            score += 10  # 适中股本
        elif shares_billion < 1:
            score -= 5   # 小盘股风险
        elif shares_billion > 15:
            score -= 5   # 超大盘股流动性
    
    return clamp(score, 0, 100)

def calculate_fundamental_score(stock_index, all_stocks_data):
    """计算股票的基本面评分（方案二实现）"""
    import random
    
    # 当股票数量太少时，使用绝对评分兜底
    if not all_stocks_data or len(all_stocks_data) <= 2:
        raw_score = calculate_raw_fundamental_score(**all_stocks_data[stock_index])
        # 将0-100转换为-0.3到0.3之间（缩小范围，避免极端）
        return clamp((raw_score - 50) / 100.0, -0.3, 0.3)
    else:
        # 股票数量足够时，使用相对排名评分
        return calculate_relative_fundamental_score(stock_index, all_stocks_data)

def calculate_relative_fundamental_score(stock_index, all_stocks_data):
    """基于相对排名计算基本面评分"""
    import random
    
    # 当股票数量太少时，使用绝对评分兜底
    if not all_stocks_data or len(all_stocks_data) <= 2:
        raw_score = calculate_raw_fundamental_score(**all_stocks_data[stock_index])
        # 将0-100转换为-0.3到0.3之间
        return clamp((raw_score - 50) / 100.0, -0.3, 0.3)
    
    # 计算所有股票的原始评分
    raw_scores = []
    for stock_data in all_stocks_data:
        raw_scores.append(calculate_raw_fundamental_score(**stock_data))
    
    # 计算当前股票的排名（百分位）
    current_score = raw_scores[stock_index]
    rank = sum(1 for s in raw_scores if s < current_score)
    percentile = rank / len(raw_scores)  # 0到1之间
    
    # 将百分位转换为评分：只有前30%得正分，后30%得负分
    if percentile >= 0.7:
        # 前30%：正面评分，越靠前评分越高
        score = (percentile - 0.7) * 1.67  # 0到0.5
    elif percentile <= 0.3:
        # 后30%：负面评分，越靠后评分越低
        score = (percentile - 0.3) * 1.67  # -0.5到0
    else:
        # 中间40%：中性评分
        score = 0.0
    
    # 添加随机波动，增加市场不确定性
    random_factor = random.uniform(-0.1, 0.1)
    score += random_factor
    
    return clamp(score, -0.5, 0.5)

def test_solution2():
    """测试方案二：绝对评分兜底机制"""
    print("测试方案二：绝对评分兜底机制")
    print("=" * 70)
    
    # 测试场景1：只有两只股票
    print("\n场景1：只有两只股票（使用绝对评分兜底）")
    print("-" * 50)
    
    two_stocks_data = [
        # 优质股票
        {"pe": 8.0, "carbon": 50.0, "avg_carbon": 100.0, "happiness": 80.0, "total_shares": 50000},
        # 劣质股票
        {"pe": 25.0, "carbon": 150.0, "avg_carbon": 100.0, "happiness": 20.0, "total_shares": 50000},
    ]
    
    random.seed(42)  # 固定种子便于复现
    
    for i, stock_data in enumerate(two_stocks_data):
        score = calculate_fundamental_score(i, two_stocks_data)
        raw_score = calculate_raw_fundamental_score(**stock_data)
        
        print(f"股票{i+1}:")
        print(f"  原始评分: {raw_score:.1f}")
        print(f"  最终评分: {score:+.3f}")
        
        if score > 0.1:
            print(f"  → 倾向推高价格")
        elif score < -0.1:
            print(f"  → 倾向压低价格")
        else:
            print(f"  → 中性")
        print()
    
    # 测试场景2：三只股票（使用相对排名）
    print("\n场景2：三只股票（使用相对排名评分）")
    print("-" * 50)
    
    three_stocks_data = [
        # 优质股票
        {"pe": 8.0, "carbon": 50.0, "avg_carbon": 100.0, "happiness": 80.0, "total_shares": 50000},
        # 中等股票
        {"pe": 15.0, "carbon": 100.0, "avg_carbon": 100.0, "happiness": 50.0, "total_shares": 50000},
        # 劣质股票
        {"pe": 25.0, "carbon": 150.0, "avg_carbon": 100.0, "happiness": 20.0, "total_shares": 50000},
    ]
    
    for i, stock_data in enumerate(three_stocks_data):
        score = calculate_fundamental_score(i, three_stocks_data)
        raw_score = calculate_raw_fundamental_score(**stock_data)
        
        print(f"股票{i+1}:")
        print(f"  原始评分: {raw_score:.1f}")
        print(f"  最终评分: {score:+.3f}")
        
        if score > 0.1:
            print(f"  → 倾向推高价格")
        elif score < -0.1:
            print(f"  → 倾向压低价格")
        else:
            print(f"  → 中性")
        print()
    
    # 测试场景3：五只股票（使用相对排名）
    print("\n场景3：五只股票（使用相对排名评分）")
    print("-" * 50)
    
    five_stocks_data = [
        # 优质股票
        {"pe": 8.0, "carbon": 50.0, "avg_carbon": 100.0, "happiness": 80.0, "total_shares": 50000},
        # 良好股票
        {"pe": 12.0, "carbon": 80.0, "avg_carbon": 100.0, "happiness": 70.0, "total_shares": 50000},
        # 中等股票
        {"pe": 15.0, "carbon": 100.0, "avg_carbon": 100.0, "happiness": 50.0, "total_shares": 50000},
        # 较差股票
        {"pe": 20.0, "carbon": 120.0, "avg_carbon": 100.0, "happiness": 40.0, "total_shares": 50000},
        # 劣质股票
        {"pe": 25.0, "carbon": 150.0, "avg_carbon": 100.0, "happiness": 20.0, "total_shares": 50000},
    ]
    
    positive_count = 0
    negative_count = 0
    neutral_count = 0
    
    for i, stock_data in enumerate(five_stocks_data):
        score = calculate_fundamental_score(i, five_stocks_data)
        raw_score = calculate_raw_fundamental_score(**stock_data)
        
        if score > 0.1:
            positive_count += 1
            status = "正面(涨)"
        elif score < -0.1:
            negative_count += 1
            status = "负面(跌)"
        else:
            neutral_count += 1
            status = "中性"
        
        print(f"股票{i+1}: 原始={raw_score:.1f}, 最终={score:+.3f} ({status})")
    
    print(f"\n统计结果:")
    print(f"  正面评分(涨): {positive_count}只 ({positive_count/len(five_stocks_data)*100:.1f}%)")
    print(f"  负面评分(跌): {negative_count}只 ({negative_count/len(five_stocks_data)*100:.1f}%)")
    print(f"  中性评分: {neutral_count}只 ({neutral_count/len(five_stocks_data)*100:.1f}%)")
    
    print("\n\n方案二优势总结:")
    print("-" * 50)
    print("✅ 两只股票时：使用绝对评分，避免极端分化")
    print("✅ 三只股票时：开始使用相对排名，但仍有中性股票")
    print("✅ 五只股票时：完全使用相对排名，实现市场分化")
    print("✅ 平滑过渡：股票数量增加时，评分机制自然过渡")

if __name__ == "__main__":
    test_solution2()