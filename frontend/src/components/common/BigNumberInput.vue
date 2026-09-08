<template>
  <el-input
    class="big-number-input"
    :class="{ 'bni-invalid': invalid }"
    :model-value="display"
    :placeholder="placeholder"
    :disabled="disabled"
    :readonly="readonly"
    :size="size"
    :clearable="clearable"
    :input-style="inputStyle"
    inputmode="decimal"
    autocomplete="off"
    :title="invalid ? '请输入有效数字' : undefined"
    @update:model-value="onInput"
  >
    <template v-for="(_, name) in $slots" :key="name" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps ?? {}" />
    </template>
  </el-input>
</template>

<script setup lang="ts">
/**
 * 大数安全数字输入框（千万京 10^23 级可输入）。
 *
 * 背景：el-input-number 基于原生 Number（IEEE double），> 2^53（约 0.9 京）的
 * 值会静默丢精度，物理上无法表示。本组件用文本输入承载任意长度的数字字符串，
 * 前端只做「搬运 + 校验」，不做数值计算；后端 Python int/Decimal 天然无精度上限。
 *
 * 约定：
 * - v-model 恒为「干净的数字字符串」（已剥离千分位逗号/空格/全角逗号），空值为 ""；
 * - 非法输入（非数字、低于 min）显示红色边框提示，但仍回传字符串由表单决定是否拦截；
 * - min 仅作宽松校验（Number 比较对超大数只保留数量级，够用）；
 * - 金额显示分组请用 utils/format.ts 的 formatMoney / formatMoneyCN。
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    modelValue?: string | number | null;
    placeholder?: string;
    disabled?: boolean;
    readonly?: boolean;
    size?: "large" | "default" | "small";
    /** 允许的最小值（宽松校验）；未填则不限 */
    min?: number;
    /** 允许的最大值（宽松校验）；未填则不限 */
    max?: number;
    clearable?: boolean;
    inputStyle?: Record<string, string>;
  }>(),
  {
    modelValue: "",
    placeholder: "",
    disabled: false,
    readonly: false,
    size: "default",
    clearable: false,
    inputStyle: () => ({}),
  },
);

const emit = defineEmits<{
  (e: "update:modelValue", value: string): void;
}>();

const NUM_RE = /^[+-]?\d+(\.\d+)?$/;

/** 剥离千分位逗号 / 空格 / 全角逗号 / 下划线，容忍粘贴带分隔符的数字。 */
function clean(raw: string): string {
  return raw.replace(/[,，\s_]/g, "");
}

const display = computed(() => {
  if (props.modelValue == null) return "";
  return String(props.modelValue);
});

function onInput(raw: string) {
  emit("update:modelValue", clean(raw));
}

const invalid = computed(() => {
  const s = display.value.trim();
  if (s === "") return false; // 空值交由表单必填校验处理
  if (!NUM_RE.test(s)) return true;
  if (props.min != null && Number.isFinite(props.min)) {
    const n = Number(s);
    if (Number.isFinite(n) && n < props.min) return true;
  }
  if (props.max != null && Number.isFinite(props.max)) {
    const n = Number(s);
    if (Number.isFinite(n) && n > props.max) return true;
  }
  return false;
});
</script>

<style scoped>
.big-number-input.bni-invalid :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--el-color-danger) inset;
}
</style>
