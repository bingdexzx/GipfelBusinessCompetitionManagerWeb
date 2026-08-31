<template>
  <div class="infra-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ authStore.can("data:infrastructure:edit") ? "基建管理" : "基建" }}</h2>
      <div class="pm-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索基建"
          clearable
          style="width: 200px"
          size="default"
        />
        <el-button
          v-if="authStore.can('data:infrastructure:edit')"
          type="primary"
          @click="openCreate"
          >+ 新建</el-button
        >
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table v-loading="loading" :data="filteredData" border stripe style="width: 100%">
      <el-table-column prop="name" label="名称" min-width="150" />
      <el-table-column
        v-for="f in fields"
        :key="f.prop"
        :prop="f.prop"
        :label="f.label"
        min-width="110"
      />
      <el-table-column
        v-if="authStore.can('data:infrastructure:edit')"
        label="操作"
        width="200"
        fixed="right"
      >
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog append-to-body v-model="detailVisible" title="基建详情" width="560px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item v-for="f in fields" :key="f.prop" :label="f.label">
          {{ (detailData as any)[f.prop] }}
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ $formatTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ $formatTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑基建管理' : '新建基建管理'"
      width="640px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="140px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入基建名称" />
        </el-form-item>
        <el-form-item
          v-for="f in fields"
          :key="f.prop"
          :label="f.label"
          :prop="f.prop"
        >
          <el-input-number
            v-model="(form as any)[f.prop]"
            :min="0"
            style="width: 100%"
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

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { useCompetitionStore } from "@/stores/competition";
import { useCompetitionReload } from "@/composables/useCompetitionReload";
import { ElMessage } from "element-plus";
import { infrastructuresApi } from "@/api";
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";

interface InfraItem {
  id: number;
  name: string;
  footprint?: number;
  employmentRateBonus?: number;
  populationBonus?: number;
  highQualityPopulationBonus?: number;
  price?: number;
  happinessIndexBonus?: number;
  perCapitaIncomeBonus?: number;
  carbonReductionBonus?: number;
  activationPrice?: number;
  createdAt?: string;
  updatedAt?: string;
}

const FIELD_DEFS = [
  { prop: "footprint", label: "占地面积" },
  { prop: "employmentRateBonus", label: "就业率加成" },
  { prop: "populationBonus", label: "人口加成" },
  { prop: "highQualityPopulationBonus", label: "高素质人口加成" },
  { prop: "price", label: "价格" },
  { prop: "happinessIndexBonus", label: "幸福度加成" },
  { prop: "perCapitaIncomeBonus", label: "人均收益加成" },
  { prop: "carbonReductionBonus", label: "减碳排放加成" },
  { prop: "activationPrice", label: "启用价格" },
];
const fields = FIELD_DEFS;

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const data = ref<InfraItem[]>([]);
const loading = ref(false);
const searchText = ref("");
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref();
const detailVisible = ref(false);
const detailData = ref<InfraItem | null>(null);

const form = reactive<Record<string, any>>({
  name: "",
  footprint: 0,
  employmentRateBonus: 0,
  populationBonus: 0,
  highQualityPopulationBonus: 0,
  price: 0,
  happinessIndexBonus: 0,
  perCapitaIncomeBonus: 0,
  carbonReductionBonus: 0,
  activationPrice: 0,
});

const formRules = {
  name: [{ required: true, message: "请输入基建名称", trigger: "blur" }],
};

const filteredData = computed(() => {
  const list = Array.isArray(data.value) ? data.value : [];
  if (!searchText.value) return list;
  const q = searchText.value.toLowerCase();
  return list.filter((item) =>
    String(item?.name ?? "")
      .toLowerCase()
      .includes(q),
  );
});

onMounted(loadData);

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(loadData, () => {
  data.value = [];
});

// 实时同步：他人增删改基建后，立即刷新本列表
useResourceChanged("infrastructures", () => {
  loadData();
});

async function loadData() {
  loading.value = true;
  try {
    if (!compStore.competitionId) {
      data.value = [];
      return;
    }
    const res: any = await infrastructuresApi.list({
      page: 1,
      pageSize: 100,
      competitionId: compStore.competitionId,
    });
    data.value = Array.isArray(res) ? res : res?.items || [];
  } catch (e) {
    console.error("Failed to load infrastructures:", e);
  } finally {
    loading.value = false;
  }
}

function showDetail(row: InfraItem) {
  detailData.value = row;
  detailVisible.value = true;
}

function openCreate() {
  if (!compStore.competitionId) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editingId.value = null;
  for (const key of Object.keys(form)) form[key] = key === "name" ? "" : 0;
  dialogVisible.value = true;
}

function openEdit(row: InfraItem) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name || "";
  for (const f of fields) form[f.prop] = (row as any)[f.prop] ?? 0;
  dialogVisible.value = true;
}

async function handleDelete(row: InfraItem) {
  let impact: any = null;
  try {
    impact = await infrastructuresApi.impact(row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除
  }
  try {
    await confirmDeleteWithImpact(row.name, impact, {
      baseMessage: "确定删除该基建吗？此操作不可恢复。",
    });
    await infrastructuresApi.remove(row.id, compStore.competitionId);
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
    const body: any = { competitionId: compStore.competitionId, name: form.name };
    for (const f of fields) body[f.prop] = form[f.prop];
    try {
      if (isEdit.value && editingId.value) {
        await infrastructuresApi.update(editingId.value, body);
      } else {
        await infrastructuresApi.create(body);
      }
      ElMessage.success(isEdit.value ? "已更新" : "已创建");
      dialogVisible.value = false;
      loadData();
    } catch (e) {
      console.error("Failed to submit infrastructure:", e);
    } finally {
      submitting.value = false;
    }
  });
}

function resetForm() {
  formRef.value?.resetFields();
  for (const key of Object.keys(form)) form[key] = key === "name" ? "" : 0;
}
</script>

<style scoped>
.infra-manager {
  padding: 0;
}
.pm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.pm-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.pm-actions {
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
