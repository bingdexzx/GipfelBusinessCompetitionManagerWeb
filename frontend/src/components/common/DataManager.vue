<template>
  <div class="data-manager">
    <div class="dm-toolbar">
      <h2 class="dm-title">{{ title }}</h2>
      <div class="dm-actions">
        <el-input
          v-model="searchText"
          :placeholder="`搜索${title}`"
          clearable
          class="dm-search"
          size="default"
        />
        <el-button type="primary" v-if="canManage" @click="openCreate">+ 新建</el-button>
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <!-- 桌面 / 平板：表格 -->
    <el-table
      v-if="!isPhone"
      v-loading="loading"
      :data="filteredData"
      border
      stripe
      style="width: 100%"
    >
      <el-table-column
        v-for="col in columns"
        :key="col.prop"
        :prop="col.prop"
        :label="col.label"
        :min-width="col.minWidth"
      >
        <template v-if="col.render" #default="{ row }">
          <component :is="col.render" :row="row" :value="getNested(row, col.prop)" />
        </template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 手机：堆叠卡片，每个字段以「标签：值」竖向排列，全部信息可见、无需横滑 -->
    <div v-else class="dm-cards" v-loading="loading">
      <div v-for="row in filteredData" :key="rowKey(row)" class="dm-card">
        <div class="dm-card-head">
          <span class="dm-card-title">{{ cardTitle(row) }}</span>
        </div>
        <div class="dm-card-body">
          <div v-for="col in columns" :key="col.prop" class="dm-card-row">
            <span class="dm-card-label">{{ col.label }}</span>
            <span class="dm-card-value">
              <component
                v-if="col.render"
                :is="col.render"
                :row="row"
                :value="getNested(row, col.prop)"
              />
              <template v-else>{{ getNested(row, col.prop) ?? "—" }}</template>
            </span>
          </div>
        </div>
        <div v-if="canManage" class="dm-card-actions">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </div>
      </div>
      <div v-if="!loading && !filteredData.length" class="dm-card-empty">暂无数据</div>
    </div>

    <el-dialog append-to-body v-model="showDetail" :title="title.replace('管理', '') + '详情'" width="480px">
      <el-descriptions :column="1" border>
        <el-descriptions-item v-for="col in columns" :key="col.prop" :label="col.label">
          {{ detailRow ? getNested(detailRow, col.prop) : "" }}
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{
          detailRow?.createdAt || "-"
        }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{
          detailRow?.updatedAt || "-"
        }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog append-to-body
      v-model="dialogVisible"
      :title="isEdit ? `编辑${title}` : `新建${title}`"
      width="560px"
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px" class="dm-form" @submit.prevent>
        <el-form-item
          v-for="field in formFields"
          :key="field.prop"
          :label="field.label"
          :prop="field.prop"
          :rules="field.rules"
        >
          <el-input
            v-if="field.type === 'text' || !field.type"
            v-model="form[field.prop]"
            :type="field.inputType || 'text'"
          />
          <el-input-number
            v-else-if="field.type === 'number'"
            v-model="form[field.prop]"
            :min="field.min ?? 0"
            style="width: 100%"
          />
          <el-select
            v-else-if="field.type === 'select'"
            v-model="form[field.prop]"
            :multiple="field.multiple"
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="opt in field.options"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <el-input
            v-else-if="field.type === 'textarea'"
            v-model="form[field.prop]"
            type="textarea"
            :rows="3"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts" generic="T extends Record<string, any>">
import { ref, reactive, computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { useCompetitionStore } from "@/stores/competition";
import { useCompetitionReload } from "@/composables/useCompetitionReload";
import { useAuthStore } from "@/stores/auth";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";

interface Column {
  prop: string;
  label: string;
  width?: string | number;
  minWidth?: string | number;
  render?: any;
}

interface FormField {
  prop: string;
  label: string;
  type?: "text" | "number" | "select" | "textarea";
  inputType?: string;
  min?: number;
  multiple?: boolean;
  options?: { label: string; value: any }[];
  rules?: any[];
}

const props = defineProps<{
  title: string;
  columns: Column[];
  formFields: FormField[];
  api: {
    list: () => Promise<{ items: T[] } | T[]>;
    create: (data: any) => Promise<any>;
    update: (id: number, data: any) => Promise<any>;
    remove: (id: number, competitionId?: number | null) => Promise<any>;
    impact?: (id: number) => Promise<any>;
  };
  /** 管理（新建/编辑/删除）所需的权限键；缺省视为无需校验（始终可管理）。 */
  managePermission?: string;
}>();

const compStore = useCompetitionStore();
const authStore = useAuthStore();
// 手机端（≤640px）将表格切换为堆叠卡片，避免横向滚动导致数据展示不全
const { isPhone } = useBreakpoint();

// 是否拥有管理权限：未声明 managePermission 的模块默认视为可管理。
const canManage = computed(() => !props.managePermission || authStore.can(props.managePermission));

const data = ref<T[]>([]);
const loading = ref(false);
const searchText = ref("");
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const showDetail = ref(false);
const detailRow = ref<any>(null);
const formRef = ref();

const form = reactive<Record<string, any>>({});
const formRules = computed(() => {
  const rules: Record<string, any> = {};
  for (const field of props.formFields) {
    if (field.rules) rules[field.prop] = field.rules;
  }
  return rules;
});

const filteredData = computed(() => {
  if (!searchText.value) return data.value;
  const q = searchText.value.toLowerCase();
  return data.value.filter((item: any) =>
    props.columns.some((col) => {
      const val = getNested(item, col.prop);
      return String(val || "")
        .toLowerCase()
        .includes(q);
    }),
  );
});

function getNested(obj: any, path: string): any {
  return path.split(".").reduce((acc, part) => acc?.[part], obj);
}

function getIdField(item: any): number {
  return item.id || item._id;
}

// 卡片视图：用行 id 作为 v-for 的 key
function rowKey(row: any): number | string {
  return getIdField(row);
}

// 卡片视图：标题优先取「名称」类字段，否则取首列值，再否则取 id
function cardTitle(row: any): string {
  const nameCol = props.columns.find(
    (c) => c.prop === "name" || c.prop.endsWith(".name") || c.label.includes("名称"),
  );
  const val = nameCol ? getNested(row, nameCol.prop) : getNested(row, props.columns[0]?.prop);
  return val != null && val !== "" ? String(val) : `ID:${getIdField(row)}`;
}

onMounted(loadData);

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(loadData, () => {
  data.value = [];
});

async function loadData() {
  loading.value = true;
  try {
    if (!compStore.competitionId) {
      data.value = [];
      return;
    }
    const res: any = await (props.api as any).list({ competitionId: compStore.competitionId });
    if (Array.isArray(res)) data.value = res;
    else if (res && (res as any).items) data.value = (res as any).items;
    else data.value = [];
  } catch (e) {
    console.error("Failed to load data:", e);
  } finally {
    loading.value = false;
  }
}

function openDetail(row: any) {
  detailRow.value = row;
  showDetail.value = true;
}

function openCreate() {
  if (!compStore.competitionId) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editingId.value = null;
  dialogVisible.value = true;
  for (const field of props.formFields) {
    form[field.prop] = field.type === "number" ? 0 : "";
  }
}

function openEdit(row: any) {
  isEdit.value = true;
  editingId.value = getIdField(row);
  dialogVisible.value = true;
  for (const field of props.formFields) {
    form[field.prop] = getNested(row, field.prop) ?? (field.type === "number" ? 0 : "");
  }
}

async function handleDelete(row: any) {
  const id = getIdField(row);
  let impact: any = null;
  if ((props.api as any).impact) {
    try {
      impact = await (props.api as any).impact(id);
    } catch {
      impact = null;
    }
  }
  try {
    await confirmDeleteWithImpact(row.name ?? String(id), impact);
    await props.api.remove(id, compStore.competitionId);
    ElMessage.success("已删除");
    loadData();
  } catch {
    // 用户取消或操作失败，不处理
  }
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      if (isEdit.value && editingId.value) {
        await props.api.update(editingId.value, {
          ...form,
          competitionId: compStore.competitionId,
        });
      } else {
        await props.api.create({ ...form, competitionId: compStore.competitionId });
      }
      ElMessage.success(isEdit.value ? "已更新" : "已创建");
      dialogVisible.value = false;
      loadData();
    } catch {
      ElMessage.error("操作失败，请重试");
    } finally {
      submitting.value = false;
    }
  });
}

function resetForm() {
  formRef.value?.resetFields();
}
</script>

<style scoped>
.dm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.dm-title {
  position: relative;
  font-size: var(--font-2xl);
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
  padding-left: 14px;
  margin: 0;
}
.dm-title::before {
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
.dm-actions {
  display: flex;
  gap: 8px;
}
.dm-search {
  width: 200px;
}
@media (max-width: 640px) {
  .dm-toolbar {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .dm-actions {
    width: 100%;
  }
  .dm-search {
    flex: 1;
    width: auto;
    min-width: 0;
  }
  /* 表单标签在窄屏改为顶部堆叠，避免 label-width 挤压输入框 */
  .dm-form :deep(.el-form-item) {
    display: block;
  }
  .dm-form :deep(.el-form-item__label) {
    width: auto !important;
    text-align: left;
    padding: 0 0 4px;
    line-height: 1.4;
  }
}
.no-comp-warning {
  text-align: center;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--color-warning-soft);
  border: 1px solid rgba(var(--color-warning-soft-rgb), 0.3);
  border-radius: 6px;
  color: #b45309;
  font-size: 13px;
}

/* ===================== 手机端堆叠卡片（替代横向表格） ===================== */
.dm-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 4px;
}
.dm-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: box-shadow var(--dur-base) var(--ease-out-expo);
}
.dm-card:hover {
  box-shadow: var(--shadow-md);
}
.dm-card-head {
  padding: 12px 14px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-2);
}
.dm-card-title {
  font-weight: 700;
  font-size: var(--font-md);
  color: var(--color-text-primary);
  word-break: break-word;
}
.dm-card-body {
  padding: 2px 14px 6px;
}
.dm-card-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px dashed var(--color-border);
  font-size: var(--font-sm);
}
.dm-card-row:last-child {
  border-bottom: none;
}
.dm-card-label {
  flex-shrink: 0;
  color: var(--color-text-secondary);
}
.dm-card-value {
  flex: 1;
  min-width: 0;
  text-align: right;
  color: var(--color-text-primary);
  word-break: break-word;
}
.dm-card-actions {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  border-top: 1px solid var(--color-border);
  flex-wrap: wrap;
}
.dm-card-actions .el-button {
  flex: 1;
  margin: 0;
  min-width: 0;
}
.dm-card-empty {
  text-align: center;
  color: var(--color-text-tertiary);
  padding: 32px 0;
  font-size: var(--font-sm);
}
</style>
