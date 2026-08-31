/**
 * 本地缓存层（Web 化简化版）。
 *
 * 原 Electron 客户端使用 IndexedDB 维护「全量副本 + 增量同步」以支持离线查看与降低服务端压力。
 * Web 化重构后，新前端请求层（request.ts）改为直接走网络 + axios，不再维护 IndexedDB 全量副本，
 * 故本文件仅保留 SettingsView / 登出等场景调用的清空入口，作为兼容 shim。
 *
 * 如后续需要恢复增量同步能力，可在此处重新接入 IndexedDB。
 */

/**
 * 清空当前账号的本地缓存。
 *
 * 新架构无 IndexedDB 全量副本，此处仅清空 localStorage 中可能残留的请求缓存键，
 * 不影响 token / user / currentCompetition 等账号身份键（由 accountStorage 单独管理）。
 */
export async function clearCurrentAccountCache(): Promise<void> {
  try {
    const prefix = "gipfel:";
    const cacheSuffixes = [":cache:", ":memo:", ":full:"];
    const toRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix) && cacheSuffixes.some((s) => k.includes(s))) {
        toRemove.push(k);
      }
    }
    toRemove.forEach((k) => localStorage.removeItem(k));
  } catch {
    /* localStorage 不可用时忽略 */
  }
}
