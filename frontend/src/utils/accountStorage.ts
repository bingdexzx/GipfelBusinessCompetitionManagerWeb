/**
 * 账号命名空间本地存储隔离。
 *
 * Web 化：原 Electron Store 改为 localStorage；账号命名空间（{username}@{competitionId}）保留，
 * 确保切换账号/比赛时 token 与缓存不串档。
 */

/** 当前登录账号的命名空间标识。 */
let currentRealm = "default";

function nsKey(key: string): string {
  return `gipfel:${currentRealm}:${key}`;
}

export function setRealm(realm: string): void {
  currentRealm = realm || "default";
}

export function getRealm(): string {
  return currentRealm;
}

export function getAccountItem(key: string): string | null {
  try {
    return localStorage.getItem(nsKey(key));
  } catch {
    return null;
  }
}

export function setAccountItem(key: string, value: string): void {
  try {
    localStorage.setItem(nsKey(key), value);
  } catch {
    /* 配额或隐私模式下忽略 */
  }
}

export function removeAccountItem(key: string): void {
  try {
    localStorage.removeItem(nsKey(key));
  } catch {
    /* ignore */
  }
}

/** 清空当前账号命名空间下的全部键。 */
export function clearAccountStorage(): void {
  try {
    const prefix = `gipfel:${currentRealm}:`;
    const toRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix)) toRemove.push(k);
    }
    toRemove.forEach((k) => localStorage.removeItem(k));
  } catch {
    /* ignore */
  }
}

/** 旧版迁移：把无命名空间的旧 token 迁到 default realm（保留兼容）。 */
export function ensureStorageMigration(): void {
  try {
    const oldToken = localStorage.getItem("gipfel:token");
    if (oldToken) {
      localStorage.setItem("gipfel:default:token", oldToken);
      localStorage.removeItem("gipfel:token");
    }
  } catch {
    /* ignore */
  }
}
