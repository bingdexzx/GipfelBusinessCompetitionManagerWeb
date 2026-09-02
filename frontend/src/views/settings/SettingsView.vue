<template>
  <div class="settings">
    <h2 class="page-title">系统设置</h2>
    <div class="settings-section">
      <h3>关于</h3>
      <p>Gipfel商赛系统</p>
      <el-button @click="historyVisible = true">查看更新记录</el-button>
    </div>
    <AnnouncementHistoryDialog v-model="historyVisible" />
    <div class="settings-section">
      <h3>本地数据</h3>
      <el-button type="warning" @click="clearLocalData">清空本地缓存</el-button>
    </div>
    <div class="settings-section" v-if="isSuperAdmin">
      <h3>后端管理</h3>
      <el-button type="danger" @click="openAdmin">后端管理界面</el-button>
      <el-button type="warning" @click="openLogViewer">日志查看器</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { clearCurrentAccountCache } from "@/api/cache";
import { resetRequestMemo } from "@/api/request";
import api from "@/api";
import { removeAccountItem } from "@/utils/accountStorage";
import { useVersionStore } from "@/stores/version";
import { useAuthStore } from "@/stores/auth";
import AnnouncementHistoryDialog from "@/components/AnnouncementHistoryDialog.vue";

const historyVisible = ref(false);
const versionStore = useVersionStore();
const authStore = useAuthStore();
const isSuperAdmin = authStore.isSuperAdmin;

async function clearLocalData() {
  try {
    await ElMessageBox.confirm(
      "将清空当前账号的本地缓存（比赛、原料、公司等全部请求数据）与当前比赛选择，下次将从服务端重新加载。确定继续？",
      "清空本地缓存",
      { type: "warning" },
    );
  } catch {
    return; // 用户取消
  }
  // 清空三层缓存，确保「点击后立即见效」：
  // ① 内存请求 memo（O3 stale-while-revalidate，命中后 15s 内直接返回旧值，不清则当前会话仍显示旧数据）
  resetRequestMemo();
  // ② 持久化 IndexedDB 全量副本（按账号分库天然隔离，token/登录态保留，其他账号不受影响）
  await clearCurrentAccountCache();
  // ③ 当前比赛选择
  removeAccountItem("currentCompetition");
  // 重载页面：所有已挂载组件的 Pinia/响应式状态随之归零，从服务端重新拉取。
  // 仅清 IndexedDB 不重载，视图仍持有内存旧值 → 按钮「看起来没用」，此即原 bug 根因。
  ElMessage.success("本地缓存已清空，正在重新加载…");
  setTimeout(() => window.location.reload(), 300);
}

// 后端管理后台地址：前端经同源 nginx 提供，直接走相对路径 /admin/（无需拼端口/域名）。
// 既兼容本机开发，也兼容公网同域部署。
const adminUrl = computed(() => `/admin/`);

// 后端管理后台跳转：需「仅按钮点击可跳转、直接输入网址自动跳转回前端」。
// 点击时向后端请求一次性防直连令牌（仅 SUPER_ADMIN 可获取），拼入 /admin/?token=... 打开；
// 后端 BackendGateMiddleware 校验令牌，缺失/无效/过期则 302 重定向回前端 SPA
// （见后端 BackendTokenView + BackendGateMiddleware 网关）。
async function openAdmin() {
  try {
    const res = (await api.post("/auth/backend-token")) as { token?: string };
    const token = res?.token;
    if (!token) throw new Error("未获取到访问令牌");
    const base = adminUrl.value; // "/admin/"
    const sep = base.includes("?") ? "&" : "?";
    const url = `${base}${sep}token=${encodeURIComponent(token)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  } catch (e: unknown) {
    const msg = (e as { message?: string })?.message || "打开后端管理界面失败";
    ElMessage.error(msg);
  }
}

// 日志查看器跳转：需「仅按钮点击可跳转、直接输入网址自动跳转回前端」。
// 点击时向后端请求一次性防直连令牌（仅 SUPER_ADMIN 可获取），拼入日志查看器公网地址后打开；
// 日志查看器 index 视图校验令牌，缺失/无效/过期则 302 自动跳转回前端主站（见后端 LogViewerTokenView + 日志查看器网关）。
// 公网地址来自 /api/version 的 log_viewer_url（默认 http://127.0.0.1:8120/，部署时由 Host 派生 log.<域名>）。
async function openLogViewer() {
  try {
    const res = (await api.post("/auth/logviewer-token")) as { token?: string };
    const token = res?.token;
    if (!token) throw new Error("未获取到访问令牌");
    const base =
      versionStore.logViewerUrl ||
      `http://127.0.0.1:${versionStore.logViewerPort || 8120}/`;
    const sep = base.includes("?") ? "&" : "?";
    const url = `${base}${sep}token=${encodeURIComponent(token)}`;
    window.open(url, "_blank", "noopener,noreferrer");
  } catch (e: unknown) {
    const msg = (e as { message?: string })?.message || "打开日志查看器失败";
    ElMessage.error(msg);
  }
}
</script>

<style scoped>
.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0 0 24px;
}
.settings-section {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 24px;
  margin-bottom: 16px;
}
.settings-section h3 {
  font-size: 16px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0 0 16px;
}
.settings-section p {
  font-size: 14px;
  color: #8c8c8c;
  margin: 4px 0;
}
@media (max-width: 640px) {
  .settings-section .el-button {
    width: 100%;
    margin: 0 0 10px;
  }
  .settings-section .el-button:last-child {
    margin-bottom: 0;
  }
}
</style>
