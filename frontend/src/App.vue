<template>
  <router-view />
  <AnnouncementDialog />
  <VersionUpdateDialog />
  <MessageToastHost />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";
import AnnouncementDialog from "@/components/AnnouncementDialog.vue";
import VersionUpdateDialog from "@/components/VersionUpdateDialog.vue";
import MessageToastHost from "@/components/MessageToastHost.vue";
import { useVersionStore } from "@/stores/version";

const versionStore = useVersionStore();

// 周期复核定时器：应对运行中服务端升级导致版本不一致，或版本恢复一致后自动解锁。
let recheckTimer: ReturnType<typeof setInterval> | null = null;

onMounted(async () => {
  // 应用启动先校验版本：若版本不一致则硬封锁并弹提示。
  await versionStore.checkVersion();
  // 每 5 分钟复核一次版本一致性（校验请求自带 bypassVersionBlock，不受封锁影响）。
  recheckTimer = setInterval(() => {
    versionStore.checkVersion();
  }, 5 * 60 * 1000);
});

onUnmounted(() => {
  if (recheckTimer) clearInterval(recheckTimer);
});
</script>
