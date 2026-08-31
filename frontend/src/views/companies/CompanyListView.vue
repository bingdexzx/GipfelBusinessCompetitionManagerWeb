<template>
  <div class="company-page">
    <h2 class="page-title">{{ authStore.can("company:manage") ? "公司管理" : "公司" }}</h2>
    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>
    <el-button v-if="authStore.can('company:manage')" type="primary" @click="openCreate">新建公司</el-button>

    <el-table v-if="compStore.competitionId && !dataLoading" :data="companies" border stripe style="margin-top: 16px">
      <el-table-column prop="name" label="名称" />
      <el-table-column label="产业类型">
        <template #default="{ row }">
          <el-tag type="info" size="small">{{ row.industryType?.name || "-" }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态">
        <template #default="{ row }"
          ><el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'">{{
            row.status
          }}</el-tag></template
        >
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="$router.push(`/companies/${row.id}`)"
            >查看</el-button
          >
          <el-button
            v-if="authStore.can('company:manage')"
            size="small"
            type="danger"
            @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>
    <div v-else-if="compStore.competitionId" class="cl-loading">正在加载公司数据…</div>

    <el-dialog append-to-body v-model="showCreate" title="新建公司" width="450px">
      <el-form ref="createFormRef" :model="form" :rules="createRules" label-width="80px">
        <el-form-item label="公司名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="产业类型" prop="industryTypeId">
          <el-select
            v-model="form.industryTypeId"
            placeholder="选择产业类型"
            style="width: 100%"
            clearable
          >
            <el-option v-for="it in industryTypes" :key="it.id" :label="it.name" :value="it.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="loading" @click="handleCreate">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useCompetitionStore } from "@/stores/competition";
import { useAuthStore } from "@/stores/auth";
import api from "@/api/request";
import { useResourceChanged } from "@/realtime/useResourceChanged";

const compStore = useCompetitionStore();
const authStore = useAuthStore();

const companies = ref<any[]>([]);
const allIndustryTypes = ref<any[]>([]);
// 产业类型现由用户在「数据管理 → 产业类型」中自定义，不再按编号区间区分大小型比赛
const industryTypes = computed(() => allIndustryTypes.value);
const showCreate = ref(false);
const createFormRef = ref();
const createRules = { name: [{ required: true, message: "请输入公司名称", trigger: "blur" }] };
const loading = ref(false);
const dataLoading = ref(true);
const form = reactive({ name: "", industryTypeId: null as number | null });

// 公司查看范围过滤（与服务端 companyListScopes 对齐）：仅持 company:view（无 company:manage /
// data:region:edit）且配置了 viewCompanyScopes 的账号，公司管理界面只展示其可见范围内的公司；
// 超管 / 管理者 / 区域总览发布者展示全部。前端兜底，防止机器级全量缓存跨账号复用导致越权可见。
function filterByScope(list: any[]): any[] {
  if (!Array.isArray(list)) return [];
  const scopes = authStore.user?.viewCompanyScopes;
  const restricted =
    Array.isArray(scopes) && scopes.length > 0 &&
    authStore.can("company:view") &&
    !authStore.can("company:manage") &&
    !authStore.can("data:region:edit");
  if (!restricted) return list;
  const allow = new Set(scopes);
  return list.filter((x) => allow.has(x?.id));
}

async function loadCompanies() {
  if (!compStore.competitionId) {
    companies.value = [];
    dataLoading.value = false;
    return;
  }
  dataLoading.value = true;
  try {
    const c = await api.get("/companies", { params: { competitionId: compStore.competitionId } });
    companies.value = filterByScope(Array.isArray(c) ? c : []);
  } catch (e) {
    console.error("Failed to load companies:", e);
    companies.value = [];
  } finally {
    dataLoading.value = false;
  }
}

async function loadIndustryTypes() {
  try {
    const c = await api.get("/industry-types");
    allIndustryTypes.value = Array.isArray(c) ? c : [];
  } catch (e) {
    console.error("加载行业类型失败:", e);
    allIndustryTypes.value = [];
  }
}

onMounted(() => {
  loadCompanies();
  loadIndustryTypes();
});

watch(
  () => compStore.competitionId,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      companies.value = [];
    }
    loadCompanies();
  }
);

useResourceChanged("companies", () => {
  loadCompanies();
});

function openCreate() {
  if (!compStore.competitionId) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  form.name = "";
  form.industryTypeId = null;
  showCreate.value = true;
}

async function handleCreate() {
  if (!createFormRef.value) return;
  const valid = await createFormRef.value.validate().catch(() => false);
  if (!valid) return;
  loading.value = true;
  try {
    await api.post("/companies", {
      name: form.name,
      industryTypeId: form.industryTypeId,
      competitionId: compStore.competitionId,
    });
    ElMessage.success("公司已创建");
    showCreate.value = false;
    loadCompanies();
  } catch (e) {
    console.error("Failed to create company:", e);
  } finally {
    loading.value = false;
  }
}

async function handleDelete(row: any) {
  /* 二次确认：第一次确认意图，第二次输入公司名称确认（防误删） */
  await ElMessageBox.confirm(
    `删除公司将级联清除其所有产业字段值，此操作不可恢复。确定继续吗？`,
    "删除确认",
    { type: "warning", confirmButtonText: "继续", cancelButtonText: "取消" },
  );
  await ElMessageBox.prompt(
    `请输入公司名称「${row.name}」以确认删除`,
    "二次确认",
    {
      type: "error",
      confirmButtonText: "确认删除",
      cancelButtonText: "取消",
      inputPattern: new RegExp(`^${row.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
      inputErrorMessage: "公司名称不匹配",
      inputPlaceholder: row.name,
    },
  );
  try {
    await api.delete(`/companies/${row.id}`);
    ElMessage.success("已删除");
    loadCompanies();
  } catch (e) {
    console.error("Failed to delete company:", e);
  }
}
</script>

<style scoped>
.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0 0 16px;
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
.cl-loading {
  text-align: center;
  padding: 40px 0;
  color: #909399;
  font-size: 13px;
}
</style>
