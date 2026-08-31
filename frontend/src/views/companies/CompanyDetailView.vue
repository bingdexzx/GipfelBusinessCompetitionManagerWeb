<template>
  <div class="cdv-page">
    <div class="cdv-header">
      <el-button @click="router.push('/companies')">返回</el-button>
      <h2>{{ company?.name || "加载中..." }}</h2>
      <el-tag v-if="company?.industryType" type="info" size="small">
        {{ company.industryType?.name }}
      </el-tag>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>字段</span>
          <div class="tab-toolbar">
            <el-button size="small" :loading="fieldValuesLoading" @click="loadFieldValues"
              >刷新</el-button
            >
          </div>
        </div>
      </template>

      <el-alert
        v-if="company && company.industryTypeId == null"
        type="info"
        :closable="false"
        title="该公司未设置产业类型，没有字段"
      />
      <el-table
        v-else-if="fieldEditors.length"
        v-loading="fieldValuesLoading"
        :data="fieldEditors"
        border
        stripe
        size="small"
      >
        <el-table-column prop="name" label="字段" width="160" />
        <el-table-column label="值" min-width="440" class-name="value-col">
          <template #default="{ row }">
            <!-- 计算字段：只读，展示后端已算好的存储值（calcGraph 由服务端求值并写入 CompanyFieldValue，
                 含 CONSUMER_DEMAND 等仅服务端可算的数据源，前端不可本地重算） -->
            <template v-if="row.isCalculated">
              <span class="ro-num">{{ row.editValue }}</span>
            </template>
            <!-- 以下均为只读展示：公司字段内容只能通过合同引擎修改 -->
            <template v-else-if="row.fieldType === 'STRING'">
              <span>{{ fieldStringDisplay(row) }}</span>
            </template>
            <template v-else-if="row.fieldType === 'NUMBER'">
              <span class="ro-num">{{ row.editValue }}</span>
            </template>
            <template v-else-if="row.fieldType === 'BOOLEAN'">
              <el-tag size="small" :type="row.editValue ? 'success' : 'info'">
                {{ row.editValue ? "是" : "否" }}
              </el-tag>
            </template>
            <template v-else-if="row.fieldType === 'DICTIONARY'">
              <span v-if="!dictRows(row).length" class="dict-empty">—</span>
              <el-table v-else :data="dictRows(row)" border size="small">
                <el-table-column label="名称" prop="label" min-width="120" />
                <el-table-column label="值">
                  <template #default="{ row: entry }">{{ formatDictVal(row, entry.key) }}</template>
                </el-table-column>
              </el-table>
            </template>
            <template v-else-if="row.fieldType === 'LIST'">
              <div v-if="!row.editValue || !row.editValue.length" class="dict-empty">—</div>
              <div v-for="(it, idx) in row.editValue" :key="idx" class="dict-row">
                <span class="dict-val">{{ it }}</span>
              </div>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-alert
        v-else
        type="info"
        :closable="false"
        title="该产业类型尚未定义字段"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import api from "@/api/request";
import { companyFieldsApi } from "@/api";
import { useAuthStore } from "@/stores/auth";
import { onRealtime, offRealtime } from "@/realtime/socket";

const route = useRoute();
const router = useRouter();
const companyId = Number(route.params.id);

// ===== 公司信息 =====
const company = ref<any>(null);

// ===== 自定义字段（产业类型下定义的字段，只读展示）=====
const fieldEditors = ref<any[]>([]);
const fieldValuesLoading = ref(false);

// 字典字段的渲染行：并集「产业类型定义的字典项」与「已存储的键值」。
// 即使产业类型尚未定义字典项，也能把已存的自由键值显示出来（避免存了值却看不见）。
function dictRows(row: any): { key: string; label: string }[] {
  const cfg = row.config || {};
  const labels = new Map<string, string>();
  const entries = Array.isArray(cfg.entries) ? cfg.entries : [];
  for (const e of entries) labels.set(e?.key, e?.label || e?.key);
  const keys = new Set<string>();
  for (const e of entries) if (e && e.key) keys.add(e.key);
  if (row.editValue && typeof row.editValue === "object" && !Array.isArray(row.editValue))
    for (const k of Object.keys(row.editValue)) keys.add(k);
  return [...keys].map((k) => ({ key: k, label: labels.get(k) || k }));
}
// 字典值展示：布尔型显示「是/否」，空值显示「—」
function formatDictVal(row: any, key: string): any {
  const v = row.editValue ? row.editValue[key] : undefined;
  if (row.config?.valueType === "BOOLEAN") return v ? "是" : "否";
  if (v === "" || v == null) return "—";
  return v;
}
// 把后端存储的 value 字符串转换为可展示的值
function normalizeEditValue(field: any, rawValue: any): any {
  const cfg = field.config || {};
  if (field.fieldType === "DICTIONARY") {
    let obj: Record<string, any> = {};
    try {
      const parsed = rawValue ? JSON.parse(rawValue) : null;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed))
        obj = parsed as Record<string, any>;
    } catch {
      obj = {};
    }
    const valueType = cfg.valueType || "NUMBER";
    // 字典键 = 定义项 与 已存储键值 的并集：即使产业类型尚未定义字典项，
    // 已存在的存值（如合同写入的 {"1":10}）也不会丢失，可在界面只读展示。
    const keys = new Set<string>();
    const defaults: Record<string, any> = {};
    const entries = Array.isArray(cfg.entries) ? cfg.entries : [];
    for (const e of entries) {
      if (e && e.key) {
        keys.add(e.key);
        defaults[e.key] = e.defaultValue;
      }
    }
    for (const k of Object.keys(obj)) keys.add(k);
    const out: Record<string, any> = {};
    for (const k of keys) {
      let v = obj[k];
      if (v === undefined) v = defaults[k];
      if (valueType === "NUMBER")
        out[k] = v === "" || v == null || isNaN(Number(v)) ? 0 : Number(v);
      else if (valueType === "BOOLEAN") out[k] = v === true || v === "true";
      else out[k] = v == null ? "" : String(v);
    }
    return out;
  }
  if (field.fieldType === "LIST") {
    try {
      return rawValue ? JSON.parse(rawValue) : [];
    } catch {
      return [];
    }
  }
  if (field.fieldType === "BOOLEAN") return rawValue === "true" || rawValue === true;
  if (field.fieldType === "NUMBER")
    return rawValue === null || rawValue === undefined ? 0 : Number(rawValue);
  return rawValue ?? "";
}
async function loadFieldValues() {
  if (!company.value || company.value.industryTypeId == null) {
    fieldEditors.value = [];
    return;
  }
  fieldValuesLoading.value = true;
  try {
    const res: any = await companyFieldsApi.get(companyId);
    const fields: any[] = Array.isArray(res?.fields) ? res.fields : [];
    fieldEditors.value = fields.map((f: any) => ({
      industryFieldId: f.id,
      name: f.name,
      fieldKey: f.fieldKey,
      fieldType: f.fieldType,
      config: f.config || {},
      isCalculated: !!f.isCalculated,
      editValue: normalizeEditValue(f, f.value),
    }));
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
    fieldEditors.value = [];
  } finally {
    fieldValuesLoading.value = false;
  }
}
// ===== 加载 =====
async function load() {
  try {
    company.value = await api.get(`/companies/${companyId}`);
    loadFieldValues();
  } catch (e) {
    console.error("Failed to load company:", e);
    ElMessage.error("加载公司信息失败");
  }
}

// 文本字段展示：所在地(locaton)字段空值时显示「未设定」，其余空值显示「—」。
// 所在地存的是地图节点名称（字符串），直接展示即可。
function fieldStringDisplay(row: any): string {
  const v = row.editValue;
  if (v === "" || v == null) {
    return row.fieldKey === "location" || row.config?.isLocation ? "未设定" : "—";
  }
  return String(v);
}

// 合同执行会改写公司产业字段：监听实时广播，自动刷新字段显示，
// 避免"字段其实已变更但页面仍显示旧值"的错觉。
function handleContractChanged() {
  loadFieldValues();
}

// 公司字段写入（后端 setValues）或断线重连对账后，统一通过 resource-changed 窗口事件刷新。
// 后端 company-field:changed 已由 resource-changed.ts 转译为 resource="company-field" 的事件。
function handleResourceEvent(e: any) {
  const d = e?.detail;
  if (!d) return;
  if (d.resource === "company-field" && d.id === companyId) loadFieldValues();
}

onMounted(() => {
  load();
  onRealtime("contract:changed", handleContractChanged);
  window.addEventListener("resource-changed", handleResourceEvent);
});
onUnmounted(() => {
  offRealtime("contract:changed", handleContractChanged);
  window.removeEventListener("resource-changed", handleResourceEvent);
});
</script>

<style scoped>
.cdv-page {
  /* 容器留白由 .app-content 统一提供(28px)，此处不重复加，避免双层 padding 错位。 */
}
.cdv-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}
.cdv-header h2 {
  position: relative;
  margin: 0;
  font-size: var(--font-2xl);
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
  padding-left: 14px;
}
.cdv-header h2::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 18px;
  border-radius: 4px;
  background: var(--gradient-brand);
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tab-toolbar {
  display: flex;
  gap: 8px;
}
.dict-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
}
.dict-label {
  display: inline-block;
  min-width: 80px;
  font-size: 13px;
  color: #606266;
}
.dict-empty {
  font-size: 13px;
  color: #909399;
  padding: 4px 0 8px;
}
.ro-num {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: #303133;
}
.dict-val {
  font-variant-numeric: tabular-nums;
  color: #303133;
}
.value-col .cell {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 32px;
}
</style>
