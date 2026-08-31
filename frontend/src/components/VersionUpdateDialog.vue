<script setup lang="ts">
import { useVersionStore } from "@/stores/version";
import { getClientVersion } from "@/config";

const version = useVersionStore();

function formatLine(v: string | null) {
  return v || "未知";
}
</script>

<template>
  <el-dialog
    v-model="version.showDialog"
    title="版本不一致"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    width="440px"
  >
    <div class="version-block">
      <el-alert type="warning" :closable="false" show-icon>
        客户端版本与服务端不一致，已禁用全部功能。
      </el-alert>
      <div class="versions">
        <div>客户端版本：<b>{{ formatLine(getClientVersion()) }}</b></div>
        <div>服务端版本：<b>{{ formatLine(version.serverVersion) }}</b></div>
      </div>
      <p class="tip">系统每 5 分钟自动复核，或联系管理员获取最新版本后刷新页面。</p>
    </div>
  </el-dialog>
</template>

<style scoped>
.versions {
  margin: 16px 0;
  line-height: 1.8;
}
.tip {
  color: #909399;
  font-size: 12px;
  margin: 8px 0 0;
}
</style>
