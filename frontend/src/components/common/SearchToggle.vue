<template>
  <div class="search-toggle">
    <!-- 桌面(>1024)：始终显示内联搜索框 -->
    <el-input
      v-if="!isCompact"
      :model-value="modelValue"
      :placeholder="placeholder"
      clearable
      class="st-input"
      @update:model-value="onInput"
    >
      <template #prefix><el-icon><Search /></el-icon></template>
    </el-input>

    <!-- 平板/手机(≤1024)：默认收成放大镜按钮，点击才展开内联输入框，标题始终单行 -->
    <template v-else>
      <el-button
        v-if="!expanded"
        class="st-btn"
        text
        :icon="Search"
        :aria-label="placeholder || '搜索'"
        @click="expand"
      />
      <el-input
        v-else
        ref="inputRef"
        :model-value="modelValue"
        :placeholder="placeholder"
        clearable
        class="st-input st-input--compact"
        @update:model-value="onInput"
        @blur="onBlur"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from "vue";
import { Search } from "@element-plus/icons-vue";
import { useBreakpoint } from "@/composables/useBreakpoint";

const props = defineProps<{
  modelValue: string;
  placeholder?: string;
}>();
const emit = defineEmits<{
  "update:modelValue": [string];
}>();

// 平板/手機(≤1024)下侧栏为抽屉模式，顶栏空间紧张：搜索收成按钮，避免挤压标题
const { isCompact } = useBreakpoint();
const expanded = ref(false);
const inputRef = ref<any>();

function onInput(v: string) {
  emit("update:modelValue", v ?? "");
}
function expand() {
  expanded.value = true;
  nextTick(() => {
    // el-input 暴露 focus()；拿到实例后直接聚焦展开后的输入框
    inputRef.value?.focus?.();
  });
}
function onBlur() {
  // 失焦且为空时自动收回成按钮，释放顶栏空间，保证标题始终单行
  if (!props.modelValue) expanded.value = false;
}
</script>

<style scoped>
.search-toggle {
  display: inline-flex;
  align-items: center;
}
.st-input {
  width: 200px;
}
.st-input--compact {
  width: 160px;
}
.st-btn {
  font-size: 18px;
  margin-left: 0;
}
.st-input :deep(.el-input__prefix) {
  color: var(--color-text-tertiary, #92969e);
}
</style>
