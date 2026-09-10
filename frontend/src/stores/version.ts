import { defineStore } from "pinia";
import { ref } from "vue";
import axios from "axios";
import { getApiBaseUrl, versionBlocked, getClientVersion } from "@/config";
import { ANNOUNCEMENT } from "@/data/announcement";

/** 版本硬封锁 store：Web 化后客户端版本号来自 version.ts 常量，与服务端 /api/version 比对。 */
export const useVersionStore = defineStore("version", () => {
  const showDialog = ref(false);
  const serverVersion = ref<string | null>(null);
  const backendPort = ref<number>(8000); // 后端监听端口（来自 /api/version 的 port，默认 8000）
  const logViewerPort = ref<number>(8120); // 日志查看器端口（来自 /api/version 的 log_viewer_port，默认 8120）
  const announcement = ref<string>(ANNOUNCEMENT);
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function checkVersion() {
    try {
      const res = await axios.get(getApiBaseUrl() + "/api/version", {
        // 绕过拦截器与版本封锁（自身即校验请求）
        headers: {},
      });
      const data = res.data?.data ?? res.data;
      serverVersion.value = data?.version ?? null;
      if (typeof data?.port === "number" && data.port > 0) {
        backendPort.value = data.port;
      }
      if (typeof data?.log_viewer_port === "number" && data.log_viewer_port > 0) {
        logViewerPort.value = data.log_viewer_port;
      }
      const client = getClientVersion();
      const blocked = !!serverVersion.value && serverVersion.value !== client;
      versionBlocked.value = blocked;
      if (blocked) {
        showDialog.value = true;
        startPolling();
      } else {
        stopPolling();
      }
    } catch {
      // 服务端不可达：不封锁（允许离线登录页展示），但记录
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(() => checkVersion(), 5 * 60 * 1000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  return { showDialog, serverVersion, backendPort, logViewerPort, announcement, checkVersion };
});
