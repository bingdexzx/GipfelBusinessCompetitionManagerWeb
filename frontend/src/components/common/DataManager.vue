<script setup lang="ts">
/**
 * 通用数据管理组件：支撑原料/零件/产品/燃料/载具/仓库/生产线/基建等 11 类基础数据。
 * 由各 Manager 视图传入 columns、api、权限配置。
 */
import { ref, reactive, computed, onMounted, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { deleteConfirm } from "@/utils/deleteConfirm";
import { useCompetitionStore } from "@/stores/competition";
import { onResourceChanged } from "@/realtime/resource-changed";

export interface ColumnDef {
  prop: string;
  label: string;
  width?: number | string;
  type?: "text" | "number" | "textarea" | "select" | "json";
  options?: { label: string; value: any }[];
  required?: boolean;
  placeholder?: string;
  /** select 列的默认值（新建表单初始值） */
  default?: any;
}

const props = defineProps<{
  /** API 对象，需含 list/get/create/update/delete */
  api: {
    list: (params?: any) => Promise<any>;
    create: (data: any) => Promise<any>;
    update: (id: number, data: any) => Promise<any>;
    delete: (id: number) => Promise<any>;
  };
  /** 资源名（实时事件匹配） */
  resource: string;
  columns: ColumnDef[];
  /** 列表标题 */
  title: string;
  /** 是否需要比赛上下文（默认 true） */
  competitionScoped?: boolean;
  /** 创建表单默认值工厂 */
  defaultForm?: () => Record<string, any>;
  /** 权限 key（编辑权限） */
  editPermission?: string;
}>();

const emit = defineEmits<{
  (e: "row-click", row: any): void;
}>();

const competition = useCompetitionStore();
const loading = ref(false);
const list = ref<any[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(50);
const keyword = ref("");

const dialogVisible = ref(false);
const editing = ref<any | null>(null);
const form = reactive<Record<string, any>>({});

const competitionId = computed(() => competition.currentId);

async function loadList() {
  if (props.competitionScoped !== false && !competitionId.value) {
    list.value = [];
    return;
  }
  loading.value = true;
  try {
    const params: any = { page: page.value, pageSize: pageSize.value };
    if (props.competitionScoped !== false) params.competitionId = competitionId.value;
    const res = await props.api.list(params);
    if (Array.isArray(res)) {
      list.value = res;
      total.value = res.length;
    } else if (res?.items) {
      list.value = res.items;
      total.value = res.total ?? res.items.length;
    }
  } catch {
    list.value = [];
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editing.value = null;
  Object.keys(form).forEach((k) => delete form[k]);
  const defaults = props.defaultForm?.() || {};
  Object.assign(form, defaults);
  if (props.competitionScoped !== false) form.competitionId = competitionId.value;
  dialogVisible.value = true;
}

function openEdit(row: any) {
  editing.value = row;
  Object.keys(form).forEach((k) => delete form[k]);
  Object.assign(form, row);
  dialogVisible.value = true;
}

async function save() {
  // 校验必填
  for (const c of props.columns) {
    if (c.required && (form[c.prop] === undefined || form[c.prop] === null || form[c.prop] === "")) {
      ElMessage.warning(`请填写${c.label}`);
      return;
    }
  }
  try {
    if (editing.value) {
      await props.api.update(editing.value.id, { ...form });
      ElMessage.success("更新成功");
    } else {
      await props.api.create({ ...form });
      ElMessage.success("创建成功");
    }
    dialogVisible.value = false;
    await loadList();
  } catch {
    /* ignore */
  }
}

async function remove(row: any) {
  if (!(await deleteConfirm(`确定删除「${row.name}」？`))) return;
  try {
    await props.api.delete(row.id);
    ElMessage.success("删除成功");
    await loadList();
  } catch {
    /* ignore */
  }
}

watch([competitionId, page, pageSize], () => loadList());
onMounted(() => {
  loadList();
  // 实时事件：本资源变更时刷新
  onResourceChanged(props.resource, () => loadList());
});

defineExpose({ reload: loadList });
</script>

<template>
  <div class="data-manager page-container">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="按名称搜索"
        clearable
        style="width: 240px"
        :prefix-icon="'Search'"
        @keyup.enter="loadList"
        @clear="loadList"
      />
      <el-button @click="loadList">刷新</el-button>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>新建
      </el-button>
    </div>

    <el-table v-loading="loading" :data="list" border style="width: 100%" @row-click="(r: any) => emit('row-click', r)">
      <el-table-column
        v-for="c in columns"
        :key="c.prop"
        :prop="c.prop"
        :label="c.label"
        :width="c.width"
        show-overflow-tooltip
      >
        <template #default="{ row }">
          <span v-if="c.type === 'json'">{{ JSON.stringify(row[c.prop]) }}</span>
          <span v-else>{{ row[c.prop] }}</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ $formatTime(row.updatedAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click.stop="openEdit(row)">编辑</el-button>
          <el-button size="small" link type="danger" @click.stop="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next, sizes"
      style="margin-top: 16px; justify-content: flex-end"
    />

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? `编辑${title}` : `新建${title}`"
      width="600px"
    >
      <el-form :model="form" label-width="120px">
        <el-form-item
          v-for="c in columns"
          :key="c.prop"
          :label="c.label"
          :required="c.required"
        >
          <el-input
            v-if="c.type === 'textarea' || c.type === 'json'"
            v-model="form[c.prop]"
            type="textarea"
            :rows="3"
            :placeholder="c.placeholder"
          />
          <el-input-number
            v-else-if="c.type === 'number'"
            v-model="form[c.prop]"
            :placeholder="c.placeholder"
          />
          <el-select
            v-else-if="c.type === 'select'"
            v-model="form[c.prop]"
            :placeholder="c.placeholder"
            style="width: 100%"
          >
            <el-option
              v-for="o in c.options"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
          <el-input v-else v-model="form[c.prop]" :placeholder="c.placeholder" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}
</style>
