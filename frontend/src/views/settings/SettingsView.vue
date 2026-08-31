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
      <p>
        客户端会将请求数据缓存在本地（IndexedDB）以加速加载并支持离线查看。若服务端已重置数据库，
        本地可能残留已不存在的内容。点击下方按钮可清空<strong>当前账号</strong>的本地缓存与当前比赛选择，
        下次将从服务端重新加载（其他账号的数据不受影响）。
      </p>
      <el-button type="warning" @click="clearLocalData">清空本地缓存</el-button>
    </div>
    <div class="settings-section">
      <h3>后端管理</h3>
      <p>
        打开 Django 管理后台，可直接对业务数据做临时排查 / 修数（注意：后台写库会绕过前端业务校验，
        仅建议管理员使用）。将跳转到后端地址
        <code>{{ adminUrl }}</code>（在新标签页打开，需后端以 daphne 运行；端口取自后端
        <code>.env</code> 的 <code>PORT</code>）。
      </p>
      <el-button type="primary" @click="openAdmin">进入后端管理界面</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { clearCurrentAccountCache } from "@/api/cache";
import { resetRequestMemo } from "@/api/request";
import { removeAccountItem } from "@/utils/accountStorage";
import { useVersionStore } from "@/stores/version";
import AnnouncementHistoryDialog from "@/components/AnnouncementHistoryDialog.vue";

const historyVisible = ref(false);
const versionStore = useVersionStore();

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

// 后端管理后台地址：端口取自后端 .env 的 PORT（经 /api/version 下发），默认 8000。
// 后端改端口只需改 .env PORT 并重启，按钮自动跟随，无需改前端代码。
const adminUrl = computed(
  () => `http://127.0.0.1:${versionStore.backendPort || 8000}/admin/`,
);
function openAdmin() {
  window.open(adminUrl.value, "_blank", "noopener,noreferrer");
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
</style>
