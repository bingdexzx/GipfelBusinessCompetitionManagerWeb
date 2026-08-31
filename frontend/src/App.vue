<script setup lang="ts">
import { onMounted } from "vue";
import { useAuthStore } from "@/stores/auth";
import { useVersionStore } from "@/stores/version";
import VersionUpdateDialog from "@/components/VersionUpdateDialog.vue";

const auth = useAuthStore();
const version = useVersionStore();

onMounted(async () => {
  // 启动时校验版本（硬封锁）+ 恢复登录态
  await version.checkVersion();
  await auth.restore();
});
</script>

<template>
  <router-view />
  <VersionUpdateDialog v-model="version.showDialog" />
</template>

<style>
#app {
  width: 100%;
  height: 100vh;
}
</style>
