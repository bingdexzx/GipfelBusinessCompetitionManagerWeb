/**
 * 股票下单的「预计金额」计算（价格 × 数量，审计 T-01）。
 *
 * 从 StockMarketView.vue 抽出为纯函数，便于在 Node 侧用真实代码跑边界断言。
 *
 * 改前的实现（内联在视图里）：
 *   const intPart = resultStr.slice(0, -totalDecimals) || '0';
 * 当价格与数量都是整数时 `totalDecimals === 0`，而 `slice(0, -0)` 等价 `slice(0, 0)`
 * → `intPart` 恒为空串、被兜底成 '0'，`decPart` 反而取到结果的前两位：
 *   97 × 100  → 显示 0.97（真值 9700）
 *   100 × 100 → 显示 0.1 （真值 10000）
 * 即整数价 × 整数数量时预计金额错 2~4 个数量级。
 *
 * 计算方式保持不变（字符串 → BigInt 整数运算 → 还原小数），只修 `totalDecimals === 0`
 * 的分支；结果仍是 Number 预览值（>2^53 时可能失真，实际委托以字符串原样提交给后端精确撮合）。
 */

/** 价格 × 数量的预计金额（保留改前的「小数部分截断到 2 位」行为）。 */
export function computeEstAmount(price: unknown, quantity: unknown): number {
  try {
    const p = String(price || 0);
    const q = String(quantity || 0);
    // 验证输入是否为合法数字
    if (isNaN(Number(p)) || isNaN(Number(q))) return 0;
    // 将价格和数量转为整数运算再还原，避免浮点精度丢失
    const pParts = p.split('.');
    const qParts = q.split('.');
    const pDecimals = pParts[1]?.length || 0;
    const qDecimals = qParts[1]?.length || 0;
    const pInt = BigInt(p.replace('.', '').replace(/[^0-9]/g, '') || '0');
    const qInt = BigInt(q.replace('.', '').replace(/[^0-9]/g, '') || '0');
    const result = pInt * qInt;
    const totalDecimals = pDecimals + qDecimals;
    const resultStr = result.toString().padStart(totalDecimals + 1, '0');
    // 整数 × 整数：结果本身就是整数，不能再按小数位切分（改前在这里得到 '' → 0.xx）
    if (totalDecimals === 0) return Number(resultStr);
    const intPart = resultStr.slice(0, -totalDecimals) || '0';
    const decPart = resultStr.slice(-totalDecimals).slice(0, 2);
    return Number(`${intPart}.${decPart}`);
  } catch {
    // 降级到普通乘法
    return Math.round(Number(price || 0) * Number(quantity || 0) * 100) / 100;
  }
}
