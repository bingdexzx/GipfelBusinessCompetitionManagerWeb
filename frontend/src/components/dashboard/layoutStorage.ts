/**
 * 仪表盘布局的本地存储纯函数（审计 M-01）。
 *
 * 背景：布局存在 localStorage（按账号 + 比赛分键），而「控件类型是否已注册」取决于运行时
 * 注册表：自定义控件包是**登录后**才能拉到的（启动时无 token 会 401）。改前 loadWidgets()
 * 会把未注册类型的控件直接 filter 掉，而 widgets 有 deep watch → 200ms 后把「已裁剪」的
 * 列表回写 localStorage —— 一次登录前加载失败的会话就足以把用户已保存的自定义布局永久删除。
 *
 * 因此拆成两步：
 *   - splitStoredLayout()：未注册类型的条目**保留在存储里**，只是本次不渲染；
 *   - mergeLayoutForSave()：回写时按原存储顺序合并（已渲染的用最新状态，保留的原样带过，
 *     新增的追加到末尾），避免顺序错乱或丢条目。
 */

export interface StoredWidgetEntry {
  id?: unknown;
  type?: unknown;
  [key: string]: unknown;
}

type WithId = { id?: unknown };

/** 兼容旧版布局：仅有单一 size 的控件迁移为独立的宽 w / 高 h。 */
export function migrateLegacySizes<T = StoredWidgetEntry>(entries: unknown): T[] {
  const arr = Array.isArray(entries) ? entries : [];
  return arr.map((w) => {
    const rec = (w || {}) as Record<string, unknown>;
    if (typeof rec.size === "number" && typeof rec.w !== "number") {
      const { size, ...rest } = rec;
      void size;
      return { ...rest, w: rec.size, h: rec.size } as T;
    }
    return rec as T;
  });
}

/**
 * 拆分已保存的布局：`visible` 为本次可渲染的控件，`preserved` 为类型未注册
 * （控件包尚未加载 / 已停用）的条目 —— 它们不渲染，但**必须留在存储里**；
 * `order` 为原存储顺序的 id 列表，回写时据此还原顺序。
 */
export function splitStoredLayout<T>(
  entries: T[],
  isKnownType: (type: string) => boolean,
): { visible: T[]; preserved: T[]; order: unknown[] } {
  const visible: T[] = [];
  const preserved: T[] = [];
  const order: unknown[] = [];
  for (const w of entries || []) {
    const rec = w as { type?: unknown; id?: unknown } | null | undefined;
    if (rec && rec.id != null) order.push(rec.id);
    const type = rec?.type;
    if (typeof type === "string" && isKnownType(type)) visible.push(w);
    else preserved.push(w);
  }
  return { visible, preserved, order };
}

/**
 * 回写布局：按 `order`（原存储顺序）输出 —— 已渲染控件取当前状态、未注册的原样保留、
 * 本次会话删掉的（既不在 visible 也不在 preserved）不再输出；存储里没有的新控件追加到末尾。
 */
export function mergeLayoutForSave<T extends WithId>(
  visible: T[],
  preserved: T[],
  order: unknown[],
): T[] {
  const vis = visible || [];
  const pre = preserved || [];
  const visById = new Map<unknown, T>();
  for (const w of vis) {
    if (w && w.id != null && !visById.has(w.id)) visById.set(w.id, w);
  }
  const preById = new Map<unknown, T>();
  for (const w of pre) {
    if (w && w.id != null && !preById.has(w.id)) preById.set(w.id, w);
  }

  const merged: T[] = [];
  const emitted = new Set<unknown>();
  for (const id of order || []) {
    if (emitted.has(id)) continue;
    // 保留桶里的条目若已被「已渲染」一侧接管（同 id），以当前状态为准
    const current = visById.get(id) ?? preById.get(id);
    if (current) {
      merged.push(current);
      emitted.add(id);
    }
  }
  // 无 id 的条目无法参与排序：保留桶在前、可见在后，确保不丢
  for (const w of pre) {
    if (!(w && w.id != null)) merged.push(w);
  }
  for (const w of vis) {
    if (!(w && w.id != null)) merged.push(w);
  }
  // 本次新增（原存储里没有的 id）追加到末尾
  for (const w of vis) {
    if (w && w.id != null && !emitted.has(w.id)) {
      merged.push(w);
      emitted.add(w.id);
    }
  }
  return merged;
}
