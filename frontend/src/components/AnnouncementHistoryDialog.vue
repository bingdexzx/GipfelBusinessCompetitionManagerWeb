<template>
  <el-dialog v-model="model" title="更新记录" width="560px" append-to-body>
    <div
      v-for="(a, i) in displayAnnouncements"
      :key="a.version"
      class="ah-item"
      :class="{ 'ah-latest': i === 0 }"
    >
      <div class="ah-head">
        <span class="ah-title">{{ a.title }}</span>
        <span class="ah-meta">v{{ a.version }} · {{ a.date }}</span>
        <el-tag v-if="i === 0" size="small" type="success" effect="light">最新</el-tag>
      </div>
      <div class="ah-content" v-html="a.content"></div>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { announcements } from "@/data/announcement";

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits(["update:modelValue"]);

const model = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit("update:modelValue", v),
});

// 历史更新记录里移除「点击不再显示…查看更新记录」这一句操作指引：
// 该提示仅面向「版本更新后自动弹出的公告」（其带「不再显示」按钮），在历史记录查看场景无意义。
// 数据本身保留不动，版本更新弹窗（AnnouncementDialog）继续正常显示该句。
// 该 <p> 内部为纯文本（无嵌套标签），用 [^<]* 跨整段匹配，兼容句末标点与空白。
const STRIP_HINT_RE = /<p>[^<]*不再显示[^<]*查看更新记录[^<]*<\/p>\s*/g;

const displayAnnouncements = computed(() =>
  announcements.map((a) => ({
    ...a,
    content: a.content.replace(STRIP_HINT_RE, ""),
  })),
);
</script>

<style scoped>
.ah-item {
  padding: 16px 0;
  border-bottom: 1px solid #f0f0f0;
}
.ah-item:last-child {
  border-bottom: none;
}
.ah-latest {
  padding-top: 0;
}
.ah-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.ah-title {
  font-size: 15px;
  font-weight: 600;
  color: #1f1f1f;
}
.ah-meta {
  font-size: 12px;
  color: #8c8c8c;
}
.ah-content {
  font-size: 14px;
  line-height: 1.75;
  color: #1f1f1f;
  max-height: 46vh;
  overflow-y: auto;
  word-break: break-word;
}
.ah-content :deep(p) {
  margin: 8px 0;
}
.ah-content :deep(ul) {
  padding-left: 22px;
  margin: 8px 0;
}
.ah-content :deep(li) {
  margin: 4px 0;
}
.ah-content :deep(b) {
  font-weight: 600;
}
</style>
