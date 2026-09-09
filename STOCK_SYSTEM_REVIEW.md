# 股票系统全面审查报告

> 审查时间：2026-09-09
> 审查范围：引擎核心（engine.py）、数据模型（models.py）、API视图（views.py）、前端界面（StockMarketView.vue / StockManageView.vue）

## 问题统计

| 严重程度 | 数量 | 主要类型 |
|----------|------|----------|
| P0 严重  | 4    | 并发安全、资金安全、数据一致性 |
| P1 重要  | 5    | 核心算法、数据准确性 |
| P2 中等  | 5    | 性能、健壮性、类型安全 |
| P3 轻微  | 3    | 代码风格、一致性 |

## P0 严重问题（已修复）

1. **撤单未加数据库锁** — views.py OrderItemView.delete，select_for_update + transaction.atomic
2. **做市商现金可能为负** — engine.py 建仓前检查余额，不够则缩减数量
3. **市场回调突破涨跌停** — engine.py 波动后强制 clamp 到 limitPct 范围
4. **N+1请求风暴** — 后端 stocks 列表返回 changePct/changePrice，前端不再逐个请求K线

## P1 重要问题（已修复）

5. **撮合语义不明确** — compute_match 添加文档说明，lowest_sell 默认值修正
6. **持仓量无非负约束** — models.py 添加 clean() 验证
7. **成交量为模拟数据** — 前端移除伪数据，显示"—"
8. **大数精度丢失** — estAmount 使用 BigInt 运算
9. **自成交虚增成交量** — 做市商自成交机制优化

## P2 中等问题（已修复）

10. **异常被静默吞掉** — PbSourcesView 添加 logger.warning
11. **防抖重复刷新** — 4个独立防抖合并为1个 800ms 窗口
12. **v-for key 不安全** — 持仓列表 key 增加 stockCode 后备
13. **listOrders 缓存** — 添加 cache: false
14. **死代码 stockConfigForm** — 已删除

## P3 轻微优化（已修复）

15. **涨跌颜色不一致** — 两个视图统一为 #f5483b/#16a34a
16. **测试文件散落** — 移至 tests/ 目录
17. **自定义参数推进功能** — 已移除，简化界面

## 系统优点

- 全链路 Decimal 精度
- 下单并发安全（select_for_update）
- 多租户隔离（competition_id）
- 三级权限体系
- WebSocket 实时更新
- 防连板机制
- 做市商智能调控（基本面评分 + 动量偏置 + 估值回归）
