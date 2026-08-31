import axios, { type AxiosInstance, type AxiosRequestConfig } from "axios";
import { ElMessage } from "element-plus";
import { getApiBaseUrl, versionBlocked } from "@/config";
import { getAccountItem, removeAccountItem, clearAccountStorage } from "@/utils/accountStorage";

declare module "axios" {
  export interface AxiosRequestConfig {
    /** 绕过版本硬封锁（仅版本校验请求使用）。 */
    bypassVersionBlock?: boolean;
    /** 为 true 时请求失败不弹错误提示（后台静默同步使用）。 */
    silent?: boolean;
  }
}

const api = axios.create({ timeout: 15000 });

api.interceptors.request.use(
  (config) => {
    if (versionBlocked.value && !config.bypassVersionBlock) {
      return Promise.reject(new Error("客户端版本与服务端不一致，已禁用全部请求"));
    }
    const token = getAccountItem("token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
    config.baseURL = getApiBaseUrl() + "/api";
    return config;
  },
  (error) => Promise.reject(error),
);

export function getErrorMessage(error: unknown): string {
  const err = error as any;
  if (err?.response?.data?.message) return err.response.data.message;
  if (err?.response) {
    const status = err.response.status;
    const statusText: Record<number, string> = {
      400: "请求参数错误，请检查输入",
      401: "登录已过期，请重新登录",
      403: "没有权限执行此操作",
      404: "请求的资源不存在",
      409: "数据冲突，请刷新后重试",
      422: "请求参数校验失败",
      429: "请求过于频繁，请稍后再试",
      500: "服务器内部错误，请稍后重试",
      502: "网关错误，请确认服务已启动",
      503: "服务暂不可用，请稍后重试",
      504: "网关超时，请稍后重试",
    };
    return statusText[status] || `请求失败（错误码 ${status}）`;
  }
  return "网络错误，请检查网络连接或服务器是否启动";
}

api.interceptors.response.use(
  (response) => {
    const res = response.data;
    if (res.code !== 0) {
      ElMessage.error(res.message || "请求失败");
      return Promise.reject(new Error(res.message));
    }
    return res.data;
  },
  (error) => {
    if (error.config?.silent && error.response?.status !== 401) {
      return Promise.reject(error);
    }
    if (error.response?.status === 401) {
      const isLoginRequest = error.config?.url?.includes("/auth/login");
      if (isLoginRequest) {
        ElMessage.error(getErrorMessage(error));
      } else {
        removeAccountItem("token");
        clearAccountStorage();
        window.location.hash = "#/login";
        const backendMsg = error.response?.data?.message;
        const msg =
          backendMsg && backendMsg !== "Unauthorized" ? backendMsg : "登录已过期，请重新登录";
        ElMessage.error(msg);
        window.dispatchEvent(new CustomEvent("auth:kicked"));
      }
    } else {
      ElMessage.error(getErrorMessage(error));
    }
    return Promise.reject(error);
  },
);

export interface ApiInstance {
  get: <T = any>(url: string, config?: AxiosRequestConfig) => Promise<T>;
  post: <T = any>(url: string, data?: unknown, config?: AxiosRequestConfig) => Promise<T>;
  put: <T = any>(url: string, data?: unknown, config?: AxiosRequestConfig) => Promise<T>;
  patch: <T = any>(url: string, data?: unknown, config?: AxiosRequestConfig) => Promise<T>;
  delete: <T = any>(url: string, config?: AxiosRequestConfig) => Promise<T>;
  defaults: AxiosInstance["defaults"];
  interceptors: AxiosInstance["interceptors"];
}

/**
 * 重置请求内存 memo（兼容 shim）。
 *
 * 原 Electron 客户端在 request 层维护「O3 stale-while-revalidate」内存 memo，命中后 15s 内直接返回旧值。
 * Web 化重构后新请求层不维护该 memo，故本函数为空操作，仅保留入口供 SettingsView「清空本地缓存」调用。
 */
export function resetRequestMemo(): void {
  /* no-op：新架构不维护内存请求 memo */
}

export default api as unknown as ApiInstance;
