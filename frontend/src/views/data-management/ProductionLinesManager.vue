<template>
  <div class="pm-toolbar">
    <h2 class="pm-title">
      {{ authStore.can("data:productionLine:edit") ? "生产线管理" : "生产线" }}
    </h2>
    <div class="pm-actions">
      <el-input
        v-model="searchText"
        placeholder="搜索生产线"
        clearable
        style="width: 200px"
        size="default"
      />
      <el-button v-if="authStore.can('data:productionLine:edit')" type="primary" @click="openCreate"
        >+ 新建</el-button
      >
    </div>
  </div>

  <div v-if="!compStore.competitionId" class="no-comp-warning">
    请先在「比赛管理」中选择一个比赛
  </div>

  <el-table v-loading="loading" :data="filteredData" border stripe style="width: 100%">
    <el-table-column prop="name" label="名称" />
    <el-table-column prop="price" label="价格" />
    <el-table-column prop="laborCount" label="劳动力" />
    <el-table-column prop="maxPerYear" label="年加工上限" />
    <el-table-column
      v-if="authStore.can('data:productionLine:edit')"
      label="操作"
      width="200"
      fixed="right"
    >
      <template #default="{ row }">
        <el-button size="small" @click="showDetail(row)">详情</el-button>
        <el-button
          v-if="authStore.can('data:productionLine:edit')"
          size="small"
          @click="openEdit(row)"
          >编辑</el-button
        >
        <el-button
          v-if="authStore.can('data:productionLine:edit')"
          size="small"
          type="danger"
          @click="handleDelete(row)"
          >删除</el-button
        >
      </template>
    </el-table-column>
  </el-table>

  <el-dialog append-to-body v-model="detailVisible" title="生产线详情" width="500px">
    <el-descriptions v-if="detailData" :column="1" border>
      <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
      <el-descriptions-item label="价格">{{ detailData.price }}</el-descriptions-item>
      <el-descriptions-item label="劳动力">{{ detailData.laborCount }}</el-descriptions-item>
      <el-descriptions-item label="年加工上限">{{ detailData.maxPerYear }}</el-descriptions-item>
      <el-descriptions-item label="创建时间">{{
        $formatTime(detailData.createdAt)
      }}</el-descriptions-item>
      <el-descriptions-item label="更新时间">{{
        $formatTime(detailData.updatedAt)
      }}</el-descriptions-item>
    </el-descriptions>
  </el-dialog>

  <el-dialog append-to-body
    v-model="dialogVisible"
    :title="isEdit ? '编辑' : '新建'"
    width="480px"
    destroy-on-close
    @closed="resetForm"
  >
    <el-form ref="formRef" :model="form" :rules="formRules" label-width="110px">
      <el-form-item label="名称" prop="name"
        ><el-input v-model="form.name" placeholder="生产线名称"
      /></el-form-item>
      <el-form-item label="价格" prop="price">
        <el-input-number v-model="form.price" :min="0" :precision="2" style="width: 100%" />
      </el-form-item>
      <el-form-item label="劳动力数量" prop="laborCount">
        <el-input-number v-model="form.laborCount" :min="1" :step="1" style="width: 100%" />
      </el-form-item>
      <el-form-item label="年加工上限" prop="maxPerYear">
        <el-input-number v-model="form.maxPerYear" :min="0" :precision="2" style="width: 100%" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { useCompetitionStore } from "@/stores/competition";
import { useCompetitionReload } from "@/composables/useCompetitionReload";
import { ElMessage } from "element-plus";
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";
import api from "@/api/request";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const data = ref<any[]>([]);
const loading = ref(false);
const searchText = ref("");
const filteredData = computed(() => {
  const list = Array.isArray(data.value) ? data.value : [];
  if (!searchText.value) return list;
  const q = searchText.value.toLowerCase();
  return list.filter((p: any) => String(p?.name ?? "").toLowerCase().includes(q));
});

const detailVisible = ref(false),
  detailData = ref<any>(null);
function showDetail(row: any) {
  detailData.value = row;
  detailVisible.value = true;
}

const dialogVisible = ref(false),
  isEdit = ref(false),
  editingId = ref(0);
const submitting = ref(false),
  formRef = ref();

const form = reactive({ name: "", price: 0, laborCount: 1, maxPerYear: 0 });
const formRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  price: [{ required: true, message: "请输入价格", trigger: "blur" }],
  laborCount: [{ required: true, message: "请输入劳动力数量", trigger: "blur" }],
  maxPerYear: [{ required: true, message: "请输入年加工上限", trigger: "blur" }],
};

onMounted(loadData);

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(loadData, () => {
  data.value = [];
});

useResourceChanged("production-lines", () => {
  loadData();
});
async function loadData() {
  loading.value = true;
  if (!compStore.competitionId) {
    data.value = [];
    loading.value = false;
    return;
  }
  try {
    const res = await api.get("/production-lines", {
      params: { competitionId: compStore.competitionId },
    });
    data.value = Array.isArray(res) ? res : [];
  } catch (e) {
    console.error("Failed to load production lines:", e);
    data.value = [];
  } finally {
    loading.value = false;
  }
}
function openCreate() {
  if (!compStore.competitionId) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editingId.value = 0;
  form.name = "";
  form.price = 0;
  form.laborCount = 1;
  form.maxPerYear = 0;
  dialogVisible.value = true;
}
function openEdit(row: any) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name;
  form.price = row.price;
  form.laborCount = row.laborCount;
  form.maxPerYear = row.maxPerYear;
  dialogVisible.value = true;
}
function resetForm() {
  formRef.value?.resetFields();
}

async function handleSubmit() {
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      const body = { ...form, competitionId: compStore.competitionId };
      if (isEdit.value) {
        await api.patch(`/production-lines/${editingId.value}`, body);
        ElMessage.success("已更新");
      } else {
        await api.post("/production-lines", body);
        ElMessage.success("已创建");
      }
      dialogVisible.value = false;
      loadData();
    } catch (e) {
      console.error("Failed to submit production line:", e);
    } finally {
      submitting.value = false;
    }
  });
}
async function handleDelete(row: any) {
  let impact: any = null;
  try {
    impact = await api.get(`/production-lines/${row.id}/impact`, { cache: false });
  } catch {
    impact = null;
  }
  try {
    await confirmDeleteWithImpact(row.name, impact);
    await api.delete(`/production-lines/${row.id}`, {
      params: { competitionId: compStore.competitionId },
    });
    ElMessage.success("已删除");
    loadData();
  } catch (e) {
    console.error("Failed to delete production line:", e);
  }
}
</script>

<style scoped>
.pm-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
