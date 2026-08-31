<template>
  <el-dialog
    :model-value="visible"
    :title="current.title"
    width="540px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    append-to-body
    @update:model-value="onVisibleChange"
  >
    <div class="announcement-date">{{ current.date }}</div>
    <div class="announcement-content" v-html="current.content"></div>
    <template #footer>
      <el-button type="primary" @click="onConfirm">确 定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { storeToRefs } from "pinia";
import { useAnnouncementStore } from "@/stores/announcement";

import { ref } from "vue";

const store = useAnnouncementStore();
const { visible } = storeToRefs(store);
const current = store.current;
const confirming = ref(false);

/** 用户点击「不再显示」：标记已读并关闭。 */
function onConfirm() {
  confirming.value = true;
  store.confirm();
}

/** 防止通过其它途径（遮罩/ESC）关闭弹窗导致未标记已读；唯一关闭入口为「确认」。 */
function onVisibleChange(val: boolean) {
  if (!val && !confirming.value) visible.value = true;
}
</script>

<style scoped>
.announcement-date {
  font-size: 13px;
  color: #8c8c8c;
  margin-bottom: 12px;
}
.announcement-content {
  font-size: 14px;
  line-height: 1.75;
  color: #1f1f1f;
  max-height: 52vh;
  overflow-y: auto;
  word-break: break-word;
}
.announcement-content :deep(p) {
  margin: 8px 0;
}
.announcement-content :deep(ul) {
  padding-left: 22px;
  margin: 8px 0;
}
.announcement-content :deep(li) {
  margin: 4px 0;
}
.announcement-content :deep(b) {
  font-weight: 600;
}
</style>
