import { defineStore } from "pinia";
import { ref } from "vue";
import { getServerUrl, setServerUrl as setUrl, getApiBaseUrl } from "@/config";

/** 系统设置 store：服务端地址等。 */
export const useConfigStore = defineStore("config", () => {
  const serverUrl = ref(getServerUrl());

  /** 从本地存储载入服务端地址（启动 / 进入设置页时调用）。 */
  async function loadConfig() {
    serverUrl.value = getServerUrl();
  }

  /** 获取当前 API 基础地址（请求拦截器据此拼接 URL）。 */
  function getBaseUrl(): string {
    return getApiBaseUrl();
  }

  function setServerUrl(url: string) {
    setUrl(url);
    serverUrl.value = url;
  }

  return { serverUrl, loadConfig, getBaseUrl, setServerUrl };
});
