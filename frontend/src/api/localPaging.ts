/**
 * 本地全量副本 → 组件期望的响应形态。
 *
 * 背景：GET 走的是「本地 IndexedDB 全量副本 + 增量同步」的缓存层，组件拿到的数据由
 * `fetchFullSync()` 循环分页拉全（LARGE_PAGE_SIZE + 循环取满 total），本地副本本身就是全量。
 * `applyLocalPaging()` 负责把这份全量副本按调用方给的分页参数「还原」成响应形态。
 *
 * 独立成模块的原因：这段逻辑是纯函数，抽出来才能在 Node 侧用真实代码跑单测
 * （审计 A-01 / V-04 / W-05：未传 pageSize 的调用点被默认切成 50 条，列表静默丢数据）。
 */
export type LocalPagingShape = "array" | "paged";

/** 单页最大条数（与 request.ts 的全量同步 LARGE_PAGE_SIZE 一致）。 */
export const MAX_PAGE_SIZE = 10000;

/**
 * 把外部传入的分页参数收敛成「>=1 的整数」，非法值一律退回 `fallback`。
 *
 * 审计 F-12：改前直接 `parseInt(String(params.page))`，调用方透传 `?page=0` / `?page=-1` /
 * `?page=abc` / `?pageSize=0` 时 `start` 变成负数或 NaN，`items.slice()` 会返回空数组或
 * 「从末尾倒着取一页」，而 `total` 仍为真实条数 —— 列表显示「暂无数据」却总数不为 0，
 * 属静默错误数据（不抛异常）。
 */
function toPositiveInt(value: unknown, fallback: number, max?: number): number {
  if (value == null || value === "") return fallback;
  const n = typeof value === "number" ? value : Number(String(value).trim());
  if (!Number.isFinite(n)) return fallback;
  const int = Math.trunc(n);
  if (int < 1) return fallback;
  return max != null ? Math.min(int, max) : int;
}

/**
 * 按集合 shape 与请求的分页参数还原响应。
 *
 * - `shape === "array"`：裸数组接口，原样返回；
 * - `page` 缺省 1，非法值（0 / 负数 / 非数字）同样按 1 处理；
 * - `pageSize` 缺省为**本地全量条数** —— 本地副本就是全量（fetchFullSync 已循环取满），
 *   改前缺省按 50 切片，导致所有未传 pageSize 的调用点静默只显示前 50 条
 *   （账号 20 / 公司 / 比赛 / 合同 / 科技树 / 燃料 / 收件箱等 20+ 处，且这些页面没有
 *   分页控件可以翻到后面，数据等于不可见、不可管理）；非法值同样退回全量；
 * - `pageSize` 上限 {@link MAX_PAGE_SIZE}，避免调用方传入超大值（审计 F-12）；
 * - 显式传入合法 `page` / `pageSize` 时仍按页切片（审计日志等分页页面的行为不变）。
 */
export function applyLocalPaging(
  items: unknown[],
  shape: LocalPagingShape,
  params: Record<string, unknown>,
): unknown {
  if (shape === "array") return items;
  const total = items.length;
  const page = toPositiveInt(params.page, 1);
  const pageSize = toPositiveInt(params.pageSize, total, MAX_PAGE_SIZE);
  const start = (page - 1) * pageSize;
  return { items: items.slice(start, start + pageSize), total, page, pageSize };
}
