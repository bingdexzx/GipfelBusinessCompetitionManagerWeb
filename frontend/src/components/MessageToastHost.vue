<script setup lang="ts">
import { onMounted, onBeforeUnmount } from "vue";
import { useMessageStore } from "@/stores/message";
import { onRealtime, offRealtime } from "@/realtime/socket";

const store = useMessageStore();

const handler = (payload: any) => {
  if (!payload) return;
  store.pushToast({
    id: payload.id ?? Date.now(),
    title: payload.title || "新消息",
    content: payload.content || "",
    senderName: payload.senderName,
    images: payload.images || [],
    createdAt: payload.createdAt || new Date().toISOString(),
  });
};

onMounted(() => onRealtime("message:received", handler));
onBeforeUnmount(() => offRealtime("message:received", handler));
</script>

<template>
  <div class="toast-host">
    <transition-group name="toast">
      <div v-for="t in store.toasts" :key="t.id" class="toast">
        <div class="toast-header">
          <span class="title">{{ t.title }}</span>
          <el-icon class="close" @click="store.dismissToast(t.id)"><Close /></el-icon>
        </div>
        <div class="toast-body">{{ t.content }}</div>
      </div>
    </transition-group>
  </div>
</template>

<style scoped lang="scss">
.toast-host {
  position: fixed;
  right: 16px;
  bottom: 16px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast {
  width: 320px;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}
.toast-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
  .title {
    font-weight: 600;
  }
  .close {
    cursor: pointer;
    color: #909399;
  }
}
.toast-body {
  padding: 12px;
  font-size: 13px;
  color: #606266;
  max-height: 200px;
  overflow: auto;
}
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
