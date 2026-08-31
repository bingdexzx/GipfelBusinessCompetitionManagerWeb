<script setup lang="ts">
import { onMounted, watch } from "vue";
import { useRouter } from "vue-router";
import Sidebar from "./Sidebar.vue";
import TopBar from "./TopBar.vue";
import MessageToastHost from "@/components/MessageToastHost.vue";
import { useAuthStore } from "@/stores/auth";
import { useConfigStore } from "@/stores/config";
import { useCompetitionStore } from "@/stores/competition";
import { useMessageStore } from "@/stores/message";
import { onReconnect } from "@/realtime/socket";

const router = useRouter();
const auth = useAuthStore();
const config = useConfigStore();
const competition = useCompetitionStore();
const message = useMessageStore();

onMounted(async () => {
  // 拉取账号资料后：归属比赛的账号（competitionId 非空）自动锁定并显示所属比赛，
  // 无需手动选择，也避免 localStorage 残留其他比赛导致请求越权（403）。
  // 超管 / 未分配账号（competitionId 为空）保持原手动选择逻辑。
  await auth.fetchProfile();
  await competition.applyOwnCompetition(auth.user?.competitionId ?? null);
  await competition.load();
  // 初始化消息中心实时监听并拉取未读红点（仅 message:view 权限账号生效，其余静默）。
  message.initRealtime();
  message.fetchUnread();
  config.loadConfig();

  // 断线重连后重新订阅当前比赛
  onReconnect(() => {
    if (competition.currentId) {
      // subscribeCompetition 已在 socket.ts 内处理重订
    }
  });
});

// 强制改密：拉取资料后发现仍需改密，跳回登录页触发改密对话框
watch(
  () => auth.needsPasswordChange,
  (need) => {
    if (need) router.push("/login");
  },
  { immediate: true },
);
</script>

<template>
  <div class="app-layout">
    <Sidebar />
    <div class="app-main">
      <TopBar />
      <main class="app-content">
        <router-view v-slot="{ Component }">
          <component :is="Component" />
        </router-view>
      </main>
    </div>
    <MessageToastHost />
  </div>
</template>

<style scoped lang="scss">
.app-layout {
  display: flex;
  height: 100vh;
}
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.app-content {
  flex: 1;
  overflow: auto;
  background: var(--el-bg-color-page, #f5f7fa);
}
</style>
