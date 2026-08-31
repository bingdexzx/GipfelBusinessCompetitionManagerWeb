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
import { useAnnouncementStore } from "@/stores/announcement";
import { useVersionStore } from "@/stores/version";

const announcementStore = useAnnouncementStore();
const versionStore = useVersionStore();

// 周期复核定时器：应对运行中服务端升级导致版本不一致，或版本恢复一致后自动解锁。
let recheckTimer: ReturnType<typeof setInterval> | null = null;

onMounted(async () => {
  // 应用启动先校验版本：若版本不一致则硬封锁并弹提示。
  // 注意：公告弹窗与版本封锁解耦——无论是否处于封锁状态都判定「是否应弹公告」，
  // 避免新软件首启时恰逢客户端/服务端版本短暂不一致而导致公告被永久跳过：
  // 封锁期间公告处于隐藏待显示态，封锁解除（版本恢复一致）后自动显现。
  await versionStore.checkVersion();
  announcementStore.maybeOpen();
  // 每 5 分钟复核一次版本一致性（校验请求自带 bypassVersionBlock，不受封锁影响）。
  recheckTimer = setInterval(() => {
    versionStore.checkVersion();
  }, 5 * 60 * 1000);
});

onUnmounted(() => {
  if (recheckTimer) clearInterval(recheckTimer);
});
</script>
