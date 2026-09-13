import { ElMessageBox } from "element-plus";

import { buildDeleteConfirmMessage } from "./deleteConfirmMessage";

export interface DeleteImpactItem {
  label: string;
  count: number;
}

export interface DeleteImpact {
  name?: string;
  children?: DeleteImpactItem[];
}

/**
 * 删除前的二次确认。
 * - 若该数据存在级联子数据（impact.children 非空），展示危险提示并逐项列出
 *   将被级联删除的关联数据条数，要求用户显式确认级联删除。
 * - 无级联子数据时仅做普通删除确认。
 *
 * @param name   数据名称（用于提示文案）
 * @param impact 后端返回的级联影响信息（getDeleteImpact），失败或为空时按普通删除处理
 */
export async function confirmDeleteWithImpact(
  name: string,
  impact?: DeleteImpact | null,
  options?: { baseMessage?: string; confirmText?: string },
): Promise<void> {
  const children = impact?.children || [];
  const total = children.reduce((sum, c) => sum + (c.count || 0), 0);

  if (total <= 0) {
    const msg = options?.baseMessage || `确定删除「${name}」？删除后不可恢复。`;
    await ElMessageBox.confirm(msg, "确认删除", { type: "warning" });
    return;
  }

  // 文案由纯函数生成（动态值已 HTML 转义）：本确认框以 dangerouslyUseHTMLString 渲染，
  // 未转义的数据名称即存储型 XSS（审计 F-02）。
  const msg = buildDeleteConfirmMessage(name, children);
  await ElMessageBox.confirm(msg, "级联删除警告", {
    type: "warning",
    dangerouslyUseHTMLString: true,
    confirmButtonText: options?.confirmText || "确认级联删除",
    cancelButtonText: "取消",
  });
}
