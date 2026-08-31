<template>
  <div class="toast-host" aria-live="polite">
    <transition-group name="toast" tag="div" class="toast-stack">
      <div v-for="t in toasts" :key="t.key" class="toast-card" @click="close(t.key)">
        <div class="toast-icon"><Bell /></div>
        <div class="toast-body">
          <div class="toast-head">
            <span class="toast-title">{{ t.title }}</span>
            <span v-if="t.senderName" class="toast-sender">{{ t.senderName }}</span>
          </div>
          <div class="toast-content">{{ t.content }}</div>
        </div>
        <button class="toast-close" title="关闭" @click.stop="close(t.key)">
          <Close />
        </button>
        <span class="toast-progress"></span>
      </div>
    </transition-group>
  </div>
</template>

<script setup lang="ts">
import { storeToRefs } from "pinia";
import { useMessageStore } from "@/stores/message";

const messageStore = useMessageStore();
const { toasts } = storeToRefs(messageStore);

function close(key: string) {
  messageStore.removeToast(key);
}
</script>

<style scoped>
.toast-host {
  position: fixed;
  top: 64px;
  right: 18px;
  z-index: 4000;
  pointer-events: none;
}
.toast-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: flex-end;
}
.toast-card {
  pointer-events: auto;
  position: relative;
  width: 320px;
  display: flex;
  gap: 12px;
  padding: 14px 14px 16px;
  background: var(--color-surface, #fff);
  border: 1px solid var(--color-border, #e8eaef);
  border-radius: var(--radius, 12px);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16);
  cursor: pointer;
  overflow: hidden;
}
.toast-icon {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: var(--gradient-brand-soft, #eef0ff);
  color: var(--color-primary, #6366f1);
  font-size: 18px;
}
.toast-body {
  flex: 1 1 auto;
  min-width: 0;
}
.toast-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}
.toast-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text, #1f2330);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.toast-sender {
  flex: 0 0 auto;
  font-size: 12px;
  color: var(--color-text-tertiary, #9aa1ad);
}
.toast-content {
  font-size: 13px;
  line-height: 1.55;
  color: var(--color-text-secondary, #51586a);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}
.toast-close {
  flex: 0 0 auto;
  border: none;
  background: transparent;
  color: var(--color-text-tertiary, #9aa1ad);
  cursor: pointer;
  font-size: 15px;
  padding: 2px;
  line-height: 1;
}
.toast-close:hover {
  color: var(--color-text, #1f2330);
}
/* 自动关闭进度条（6s 与 store 中 AUTO_CLOSE_MS 对齐） */
.toast-progress {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 3px;
  width: 100%;
  transform-origin: left center;
  background: var(--gradient-brand, linear-gradient(90deg, #6366f1, #06b6d4));
  animation: toast-progress 6s linear forwards;
}
@keyframes toast-progress {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}

/* 滑入（从右侧进入屏幕）/ 滑出（向右退出屏幕）动画 */
.toast-enter-active,
.toast-leave-active {
  transition: transform 0.42s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.42s ease;
}
.toast-enter-from {
  transform: translateX(120%);
  opacity: 0;
}
.toast-enter-to {
  transform: translateX(0);
  opacity: 1;
}
.toast-leave-from {
  transform: translateX(0);
  opacity: 1;
}
.toast-leave-to {
  transform: translateX(120%);
  opacity: 0;
}
/* 离场时其它卡片平滑上移补位 */
.toast-leave-active {
  position: absolute;
  right: 0;
}
</style>
