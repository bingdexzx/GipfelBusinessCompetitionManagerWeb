import { ElMessageBox } from "element-plus";

/**
 * 两步删除确认（对应项目记忆约束：删除 Company 等敏感对象需提示 + 名称校验）。
 * @param name 待删除对象的名称（需用户输入匹配）
 * @param label 提示文案中的对象类型
 */
export async function deleteConfirmWithMatch(
  name: string,
  label = "对象",
): Promise<boolean> {
  try {
    await ElMessageBox.confirm(
      `此操作将永久删除该${label}，且不可恢复。确定继续？`,
      "危险操作确认",
      { type: "warning", confirmButtonText: "继续", cancelButtonText: "取消" },
    );
    const { value } = await ElMessageBox.prompt(
      `请输入${label}名称「${name}」以确认删除：`,
      "二次确认",
      {
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
        inputPlaceholder: name,
        inputValidator: (v) => v === name || `请输入正确的${label}名称`,
      },
    );
    return value === name;
  } catch {
    return false;
  }
}

/** 普通单步删除确认。 */
export async function deleteConfirm(message = "确定删除此项？"): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, "确认删除", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
    return true;
  } catch {
    return false;
  }
}
