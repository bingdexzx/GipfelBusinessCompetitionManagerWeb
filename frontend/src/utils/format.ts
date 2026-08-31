/**
 * 前端通用格式化工具（唯一真源）。
 * 消除多个视图中重复的匿名格式化函数（金额千分位、ISO 时间截断等）。
 */

/** 金额格式化：中文千分位、最多 2 位小数；null/NaN 显示"—"（与两处股票视图原 fmt 一致）。 */
export function formatMoney(n: number | null | undefined): string {
  if (n == null || isNaN(Number(n))) return "—";
  return Number(n).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

/**
 * ISO 时间去秒截断（与全局 $formatTime 完全一致）。
 * 空值或非法日期返回 "-"；否则按 UTC 截断到秒（YYYY-MM-DD HH:mm:ss）。
 */
export function formatTime(val: string | Date | null | undefined): string {
  if (!val) return "-";
  const d = typeof val === "string" ? new Date(val) : val;
  if (isNaN(d.getTime())) return "-";
  return d.toISOString().replace("T", " ").substring(0, 19);
}
