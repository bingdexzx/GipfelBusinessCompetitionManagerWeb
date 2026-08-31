<template>
  <div class="mc-cards" v-loading="loading">
    <div v-for="(row, idx) in data" :key="rowKey ? rowKey(row) : idx" class="mc-card">
      <div class="mc-card-head">
        <span class="mc-card-title">{{ titleFor(row) }}</span>
      </div>
      <div class="mc-card-body">
        <div v-for="col in columns" :key="colKey(col)" class="mc-row">
          <span class="mc-label">{{ col.label }}</span>
          <span class="mc-value">
            <slot v-if="col.slot" :name="col.slot" :row="row" />
            <template v-else>{{ cellValue(row, col) }}</template>
          </span>
        </div>
      </div>
      <div v-if="$slots.actions" class="mc-actions">
        <slot name="actions" :row="row" />
      </div>
    </div>
    <div v-if="!loading && !data.length" class="mc-empty">{{ emptyText }}</div>
  </div>
</template>

<script setup lang="ts">
interface MobileColumn {
  prop?: string;
  label: string;
  formatter?: (row: any) => any;
  slot?: string;
}

const props = withDefaults(
  defineProps<{
    data: any[];
    columns: MobileColumn[];
    loading?: boolean;
    rowKey?: (row: any) => string | number;
    titleKey?: string;
    emptyText?: string;
  }>(),
  { loading: false, titleKey: "name", emptyText: "暂无数据" },
);

// 支持点路径取值（如 "company.name"），与 DataManager 的 getNested 保持一致。
function getNested(row: any, path?: string): any {
  if (!path || !row) return undefined;
  return path.split(".").reduce((acc, k) => (acc == null ? acc : acc[k]), row);
}

function cellValue(row: any, col: MobileColumn): any {
  if (col.formatter) return col.formatter(row);
  return getNested(row, col.prop);
}

function colKey(col: MobileColumn): string {
  return col.prop || col.slot || col.label;
}

function titleFor(row: any): string {
  const t = getNested(row, props.titleKey);
  if (t != null && t !== "") return String(t);
  const first = props.columns[0];
  const fv = first ? cellValue(row, first) : undefined;
  if (fv != null && fv !== "") return String(fv);
  return "未命名";
}
</script>

<style scoped>
.mc-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.mc-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.mc-card-head {
  padding: 10px 14px;
  background: var(--color-surface-2);
  border-bottom: 1px solid var(--color-border);
}
.mc-card-title {
  font-size: var(--font-md, 15px);
  font-weight: 600;
  color: var(--color-text-primary);
  word-break: break-word;
}
.mc-card-body {
  padding: 4px 14px;
}
.mc-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--color-border);
}
.mc-row:last-child {
  border-bottom: none;
}
.mc-label {
  flex-shrink: 0;
  max-width: 42%;
  font-size: var(--font-sm, 13px);
  color: var(--color-text-secondary);
}
.mc-value {
  flex: 1;
  text-align: right;
  font-size: var(--font-sm, 13px);
  color: var(--color-text-primary);
  word-break: break-word;
}
.mc-actions {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--color-border);
}
.mc-actions :deep(.el-button) {
  flex: 1;
}
.mc-empty {
  text-align: center;
  padding: 24px;
  color: var(--color-text-secondary);
  font-size: var(--font-sm, 13px);
}
</style>
