#!/usr/bin/env python3
"""测试调整后的做市商干预程度"""
import random

def test_reduced_intervention():
    """测试调整后的做市商干预程度"""
    print("测试调整后的做市商干预程度")
    print("=" * 70)
    
    # 调整前的参数
    old_params = {
        "mmDepthPct": 0.001,
        "mmMinQty": 1000,
        "mmMaxQty": 100000,
        "mmSpreadPct": 0.02,
        "mmSkewPct": 0.02,
        "regressionPct": 0.02,
        "mmSelfTradePct": 0.005,
        "mmSelfTradeQtyPct": 0.1,
        "mmBadNewsProb": 0.05,
        "mmGoodNewsProb": 0.03,
        "mmBadNewsImpact": 0.10,
        "mmGoodNewsImpact": 0.065,
        "mmRegressionThreshold": 0.2,
        "mmRegressionStrength": 0.5,
        "intervention_rounds": 2,  # 干预门槛轮数
        "intervention_multiplier": 3,  # 干预数量倍数
    }
    
    # 调整后的参数
    new_params = {
        "mmDepthPct": 0.0005,
        "mmMinQty": 500,
        "mmMaxQty": 50000,
        "mmSpreadPct": 0.015,
        "mmSkewPct": 0.015,
        "regressionPct": 0.015,
        "mmSelfTradePct": 0.003,
        "mmSelfTradeQtyPct": 0.05,
        "mmBadNewsProb": 0.03,
        "mmGoodNewsProb": 0.02,
        "mmBadNewsImpact": 0.06,
        "mmGoodNewsImpact": 0.04,
        "mmRegressionThreshold": 0.25,
        "mmRegressionStrength": 0.3,
        "intervention_rounds": 3,
        "intervention_multiplier": 2,
    }
    
    print("\n1. 参数对比（调整前 vs 调整后）")
    print("-" * 70)
    
    # 深度参数
    print("深度相关参数:")
    print(f"  深度占比: {old_params['mmDepthPct']} → {new_params['mmDepthPct']} (减少{(1-new_params['mmDepthPct']/old_params['mmDepthPct'])*100:.0f}%)")
    print(f"  最小数量: {old_params['mmMinQty']} → {new_params['mmMinQty']} (减少{(1-new_params['mmMinQty']/old_params['mmMinQty'])*100:.0f}%)")
    print(f"  最大数量: {old_params['mmMaxQty']} → {new_params['mmMaxQty']} (减少{(1-new_params['mmMaxQty']/old_params['mmMaxQty'])*100:.0f}%)")
    
    # 偏置参数
    print("\n偏置相关参数:")
    print(f"  点差百分比: {old_params['mmSpreadPct']} → {new_params['mmSpreadPct']} (减少{(1-new_params['mmSpreadPct']/old_params['mmSpreadPct'])*100:.0f}%)")
    print(f"  偏置百分比: {old_params['mmSkewPct']} → {new_params['mmSkewPct']} (减少{(1-new_params['mmSkewPct']/old_params['mmSkewPct'])*100:.0f}%)")
    print(f"  回归偏移: {old_params['regressionPct']} → {new_params['regressionPct']} (减少{(1-new_params['regressionPct']/old_params['regressionPct'])*100:.0f}%)")
    
    # 自成交参数
    print("\n自成交参数:")
    print(f"  偏移百分比: {old_params['mmSelfTradePct']} → {new_params['mmSelfTradePct']} (减少{(1-new_params['mmSelfTradePct']/old_params['mmSelfTradePct'])*100:.0f}%)")
    print(f"  数量百分比: {old_params['mmSelfTradeQtyPct']} → {new_params['mmSelfTradeQtyPct']} (减少{(1-new_params['mmSelfTradeQtyPct']/old_params['mmSelfTradeQtyPct'])*100:.0f}%)")
    
    # 随机事件参数
    print("\n随机事件参数:")
    print(f"  利空概率: {old_params['mmBadNewsProb']} → {new_params['mmBadNewsProb']} (减少{(1-new_params['mmBadNewsProb']/old_params['mmBadNewsProb'])*100:.0f}%)")
    print(f"  利好概率: {old_params['mmGoodNewsProb']} → {new_params['mmGoodNewsProb']} (减少{(1-new_params['mmGoodNewsProb']/old_params['mmGoodNewsProb'])*100:.0f}%)")
    print(f"  利空影响: {old_params['mmBadNewsImpact']} → {new_params['mmBadNewsImpact']} (减少{(1-new_params['mmBadNewsImpact']/old_params['mmBadNewsImpact'])*100:.0f}%)")
    print(f"  利好影响: {old_params['mmGoodNewsImpact']} → {new_params['mmGoodNewsImpact']} (减少{(1-new_params['mmGoodNewsImpact']/old_params['mmGoodNewsImpact'])*100:.0f}%)")
    
    # 回归参数
    print("\n回归参数:")
    print(f"  回归阈值: {old_params['mmRegressionThreshold']} → {new_params['mmRegressionThreshold']} (增加{(new_params['mmRegressionThreshold']/old_params['mmRegressionThreshold']-1)*100:.0f}%)")
    print(f"  回归强度: {old_params['mmRegressionStrength']} → {new_params['mmRegressionStrength']} (减少{(1-new_params['mmRegressionStrength']/old_params['mmRegressionStrength'])*100:.0f}%)")
    
    # 干预门槛
    print("\n干预门槛:")
    print(f"  干预轮数: {old_params['intervention_rounds']} → {new_params['intervention_rounds']} (增加{new_params['intervention_rounds']-old_params['intervention_rounds']}轮)")
    print(f"  干预倍数: {old_params['intervention_multiplier']} → {new_params['intervention_multiplier']} (减少{(1-new_params['intervention_multiplier']/old_params['intervention_multiplier'])*100:.0f}%)")
    
    print("\n\n2. 影响程度分析")
    print("-" * 70)
    
    # 计算综合影响
    depth_impact = new_params['mmDepthPct'] / old_params['mmDepthPct']
    spread_impact = new_params['mmSpreadPct'] / old_params['mmSpreadPct']
    skew_impact = new_params['mmSkewPct'] / old_params['mmSkewPct']
    
    print("做市商影响力变化:")
    print(f"  流动性提供能力: {depth_impact*100:.1f}% (减少{(1-depth_impact)*100:.1f}%)")
    print(f"  价格影响力: {spread_impact*100:.1f}% (减少{(1-spread_impact)*100:.1f}%)")
    print(f"  方向引导能力: {skew_impact*100:.1f}% (减少{(1-skew_impact)*100:.1f}%)")
    
    print("\n\n3. 预期效果")
    print("-" * 70)
    print("✅ 做市商流动性提供减少，市场更依赖真实交易")
    print("✅ 价格波动更自然，减少人为干预痕迹")
    print("✅ 基本面影响减弱，市场更关注真实供需")
    print("✅ 随机事件影响减小，市场更稳定")
    print("✅ 回归干预门槛提高，避免过度干预")
    print("✅ 自成交影响减小，价格发现更真实")
    
    print("\n\n4. 关键改进点")
    print("-" * 70)
    print("1. 深度减少50%：做市商提供流动性减少")
    print("2. 偏置减少25%：做市商价格影响力减弱")
    print("3. 自成交减少40%：做市商自成交影响减小")
    print("4. 随机事件减少40%：市场更稳定")
    print("5. 回归阈值提高25%：干预门槛更高")
    print("6. 回归强度减少40%：干预力度更温和")
    print("7. 干预门槛提高：需要更多连续封板才干预")
    print("8. 干预倍数减少：干预数量减少33%")

if __name__ == "__main__":
    test_reduced_intervention()