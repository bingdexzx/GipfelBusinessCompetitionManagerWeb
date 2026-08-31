<template>
  <div class="data-manager">
    <div class="dm-toolbar">
      <h2 class="dm-title">{{ title }}</h2>
      <div class="dm-actions">
        <el-input
          v-model="searchText"
          :placeholder="`搜索${title}`"
          clearable
          style="width: 200px"
          size="default"
        />
        <el-button type="primary" v-if="canManage" @click="openCreate">+ 新建</el-button>
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table v-loading="loading" :data="filteredData" border stripe style="width: 100%">
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
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px" @submit.prevent>
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
</style>
