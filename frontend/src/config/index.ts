/**
 * 全局配置：服务端地址、版本硬封锁。
 *
 * Web 化调整：
 * - 默认服务端地址改为相对路径（开发由 Vite 代理 / 生产同源）
 * - 版本硬封锁来源从前端常量 version.ts 比对 /api/version（原 Electron app.getVersion）
 */
import { ref } from "vue";
import { APP_VERSION } from "@/data/version";

const STORAGE_KEY = "gipfel:serverUrl";

export const DEFAULT_SERVER_URL = ""; // 空字符串 = 同源/相对路径（开发由 Vite 代理，生产同源）

/** 版本硬封锁标志：客户端版本号与服务端 /api/version 不一致时为 true */
export const versionBlocked = ref(false);

let serverUrl = DEFAULT_SERVER_URL;
try {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved !== null) serverUrl = saved;
} catch {
  /* localStorage 不可用时忽略 */
}

export function getApiBaseUrl(): string {
  return serverUrl;
}

export function getServerUrl(): string {
  return serverUrl;
}

export function setServerUrl(url: string): void {
  serverUrl = url || DEFAULT_SERVER_URL;
  try {
    if (url) localStorage.setItem(STORAGE_KEY, url);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  // 通知缓存层与请求层重置
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("server:changed"));
  }
}

/** 客户端版本号（用于硬封锁比对）。原 Electron app.getVersion() 改为读常量。 */
export function getClientVersion(): string {
  return APP_VERSION;
}
