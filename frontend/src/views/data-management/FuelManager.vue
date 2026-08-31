<template>
  <div class="fuel-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ authStore.can("data:fuel:edit") ? "燃料管理" : "燃料" }}</h2>
      <div class="pm-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索燃料"
          clearable
          style="width: 200px"
          size="default"
        />
        <el-button
          v-if="authStore.can('data:fuel:edit')"
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
      <el-table-column prop="name" label="名称" min-width="200" />
      <el-table-column prop="pricePerLiter" label="每升价格" min-width="120" />
      <el-table-column
        v-if="authStore.can('data:fuel:edit')"
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

    <el-dialog append-to-body v-model="detailVisible" title="燃料详情" width="480px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="每升价格">{{ detailData.pricePerLiter }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ $formatTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ $formatTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑燃料管理' : '新建燃料管理'"
      width="560px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入燃料名称" />
        </el-form-item>
        <el-form-item label="每升价格" prop="pricePerLiter">
          <el-input-number v-model="form.pricePerLiter" :min="0" style="width: 100%" />
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
import { fuelsApi } from "@/api";
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";

interface FuelItem {
  id: number;
  name: string;
  pricePerLiter?: number;
  createdAt?: string;
  updatedAt?: string;
}

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const data = ref<FuelItem[]>([]);
const loading = ref(false);
const searchText = ref("");
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref();
const detailVisible = ref(false);
const detailData = ref<FuelItem | null>(null);

const form = reactive({
  name: "",
  pricePerLiter: 0,
});

const formRules = {
  name: [{ required: true, message: "请输入燃料名称", trigger: "blur" }],
  pricePerLiter: [{ required: true, message: "请输入每升价格", trigger: "blur" }],
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

// 实时同步：他人增删改燃料后，立即刷新本列表
useResourceChanged("fuels", () => {
  loadData();
});

async function loadData() {
  loading.value = true;
  try {
    if (!compStore.competitionId) {
      data.value = [];
      return;
    }
    const res: any = await fuelsApi.list({
      page: 1,
      pageSize: 100,
      competitionId: compStore.competitionId,
    });
    data.value = Array.isArray(res) ? res : res?.items || [];
  } catch (e) {
    console.error("Failed to load fuels:", e);
  } finally {
    loading.value = false;
  }
}

function showDetail(row: FuelItem) {
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
  form.name = "";
  form.pricePerLiter = 0;
  dialogVisible.value = true;
}

function openEdit(row: FuelItem) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name || "";
  form.pricePerLiter = row.pricePerLiter ?? 0;
  dialogVisible.value = true;
}

async function handleDelete(row: FuelItem) {
  let impact: any = null;
  try {
    impact = await fuelsApi.impact(row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除
  }
  try {
    await confirmDeleteWithImpact(row.name, impact, {
      baseMessage: "确定删除该燃料吗？此操作不可恢复。",
    });
    await fuelsApi.remove(row.id, compStore.competitionId);
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
    const body = {
      competitionId: compStore.competitionId,
      name: form.name,
      pricePerLiter: form.pricePerLiter,
    };
    try {
      if (isEdit.value && editingId.value) {
        await fuelsApi.update(editingId.value, body);
      } else {
        await fuelsApi.create(body);
      }
      ElMessage.success(isEdit.value ? "已更新" : "已创建");
      dialogVisible.value = false;
      loadData();
    } catch (e) {
      console.error("Failed to submit fuel:", e);
    } finally {
      submitting.value = false;
    }
  });
}

function resetForm() {
  formRef.value?.resetFields();
  form.name = "";
  form.pricePerLiter = 0;
}
</script>

<style scoped>
.fuel-manager {
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
