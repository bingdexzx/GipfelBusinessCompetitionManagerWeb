/**
 * 级联删除确认文案（纯函数，独立成模块以便单测）。
 *
 * 背景（审计 F-02）：确认框用 `dangerouslyUseHTMLString: true` 渲染，而文案里的
 * 数据名称（`name`）与影响项标签（`label`）都来自数据库、由有 `data:*:edit` 权限的
 * 账号可写 —— 未转义直接内插即可注入 `<img onerror=...>`，在**超管点删除时**执行，
 * 属于存储型 XSS（可读取 localStorage 里的 JWT）。
 */

export interface DeleteImpactLine {
  label: string;
  count: number;
}

/** HTML 文本转义（用于插入 HTML 文案的动态值）。 */
export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * 生成级联删除确认文案（HTML，动态值已转义，仅保留本函数自身的 `<b>` / `<br/>` 排版）。
 *
 * `name` 与 `label` 都来自数据库、由有 `data:*:edit` 权限的账号可写，因此必须转义：
 * 该文案会以 `dangerouslyUseHTMLString: true` 渲染，未转义即存储型 XSS（审计 F-02）。
 */
export function buildDeleteConfirmMessage(
  name: unknown,
  children?: DeleteImpactLine[] | null,
): string {
  const lines = (children || [])
    .filter((c) => (c?.count || 0) > 0)
    .map((c) => `• ${escapeHtml(c.label)}：${Number(c.count) || 0} 条`)
    .join("<br/>");
  return (
    `删除「<b>${escapeHtml(name)}</b>」将<b>级联删除</b>以下关联数据，且不可恢复：<br/><br/>` +
    `${lines}<br/><br/>确定继续删除吗？`
  );
}
