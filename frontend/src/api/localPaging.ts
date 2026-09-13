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

/**
 * 按集合 shape 与请求的分页参数还原响应。
 *
 * - `shape === "array"`：裸数组接口，原样返回；
 * - `page` 缺省 1；
 * - `pageSize` 缺省为**本地全量条数** —— 本地副本就是全量（fetchFullSync 已循环取满），
 *   改前缺省按 50 切片，导致所有未传 pageSize 的调用点静默只显示前 50 条
 *   （账号 20 / 公司 / 比赛 / 合同 / 科技树 / 燃料 / 收件箱等 20+ 处，且这些页面没有
 *   分页控件可以翻到后面，数据等于不可见、不可管理）；
 * - 显式传入 `page` / `pageSize` 时仍按页切片（审计日志等分页页面的行为不变）。
 */
export function applyLocalPaging(
  items: unknown[],
  shape: LocalPagingShape,
  params: Record<string, unknown>,
): unknown {
  if (shape === "array") return items;
  const total = items.length;
  const page = params.page != null ? parseInt(String(params.page), 10) : 1;
  const pageSize = params.pageSize != null ? parseInt(String(params.pageSize), 10) : total;
  const start = (page - 1) * pageSize;
  return { items: items.slice(start, start + pageSize), total, page, pageSize };
}
