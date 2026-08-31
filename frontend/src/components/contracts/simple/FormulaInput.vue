<template>
  <div class="formula-input">
    <el-select v-model="valueType" size="small" style="width: 120px; margin-right: 8px">
      <el-option label="常量" value="CONST" />
      <el-option label="输入字段" value="INPUT" />
      <el-option label="公式" value="FORMULA" />
    </el-select>

    <!-- 常量 -->
    <el-input-number
      v-if="valueType === 'CONST'"
      :model-value="modelValue?.value ?? 0"
      @update:model-value="updateConst"
      size="small"
      style="width: 200px"
    />

    <!-- 输入字段引用 -->
    <el-select
      v-if="valueType === 'INPUT'"
      :model-value="modelValue?.key"
      @update:model-value="updateInput"
      size="small"
      style="width: 200px"
    >
      <el-option v-for="input in inputs" :key="input.key" :label="input.label" :value="input.key" />
    </el-select>

    <!-- 公式 -->
    <el-input
      v-if="valueType === 'FORMULA'"
      :model-value="modelValue?.expr"
      @update:model-value="updateFormula"
      size="small"
      placeholder="如: amount * 0.1"
      style="width: 300px"
    >
      <template #append>
        <el-popover trigger="click" width="400">
          <template #reference>
            <el-button size="small">帮助</el-button>
          </template>
          <div class="formula-help">
            <h4>可用变量</h4>
            <ul>
              <li v-for="input in inputs" :key="input.key">
                <code>{{ input.key }}</code> - {{ input.label }}
              </li>
            </ul>
            <h4>可用函数</h4>
            <ul>
              <li><code>abs(x)</code> - 绝对值</li>
              <li><code>sqrt(x)</code> - 平方根</li>
              <li><code>round(x)</code> - 四舍五入</li>
              <li><code>floor(x)</code> - 向下取整</li>
              <li><code>ceil(x)</code> - 向上取整</li>
              <li><code>min(a, b)</code> - 最小值</li>
              <li><code>max(a, b)</code> - 最大值</li>
              <li><code>sum(...)</code> - 求和</li>
              <li><code>avg(...)</code> - 平均值</li>
            </ul>
          </div>
        </el-popover>
      </template>
    </el-input>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';

interface InputField {
  key: string;
  label: string;
  type: string;
}

const props = defineProps<{
  modelValue: any;
  inputs: InputField[];
}>();

const emit = defineEmits<{
  (e: 'update:modelValue', value: any): void;
}>();

const valueType = computed({
  get: () => props.modelValue?.type || 'CONST',
  set: (type: string) => {
    if (type === 'CONST') {
      emit('update:modelValue', { type: 'CONST', value: 0 });
    } else if (type === 'INPUT') {
      emit('update:modelValue', { type: 'INPUT', key: props.inputs[0]?.key || '' });
    } else if (type === 'FORMULA') {
      emit('update:modelValue', { type: 'FORMULA', expr: '' });
    }
  },
});

function updateConst(value: number) {
  emit('update:modelValue', { type: 'CONST', value: value ?? 0 });
}

function updateInput(key: string) {
  emit('update:modelValue', { type: 'INPUT', key });
}

function updateFormula(expr: string) {
  emit('update:modelValue', { type: 'FORMULA', expr });
}
</script>

<style scoped>
.formula-input {
  display: flex;
  align-items: center;
}

.formula-help h4 {
  margin: 12px 0 8px;
}

.formula-help ul {
  margin: 0;
  padding-left: 20px;
}

.formula-help code {
  background: #f5f7fa;
  padding: 2px 4px;
  border-radius: 2px;
  font-size: 12px;
}
</style>
