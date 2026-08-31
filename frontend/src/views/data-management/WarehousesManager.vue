<template>
  <div class="warehouses-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ authStore.can("data:warehouse:edit") ? "仓库管理" : "仓库" }}</h2>
      <div class="pm-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索仓库"
          clearable
          style="width: 200px"
          size="default"
        />
        <el-button v-if="authStore.can('data:warehouse:edit')" type="primary" @click="openCreate"
          >+ 新建</el-button
        >
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table v-loading="loading" :data="filteredData" border stripe style="width: 100%">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="capacity" label="容量" />
      <el-table-column prop="price" label="价格" />
      <el-table-column label="种类">
        <template #default="{ row }">
          <el-tag :type="typeTag(row.type)">{{ typeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column
        v-if="authStore.can('data:warehouse:edit')"
        label="操作"
        width="200"
        fixed="right"
      >
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button v-if="authStore.can('data:warehouse:edit')" size="small" @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button
            v-if="authStore.can('data:warehouse:edit')"
            size="small"
            type="danger"
            @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <el-dialog append-to-body v-model="detailVisible" title="仓库详情" width="500px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="容量">{{ detailData.capacity }}</el-descriptions-item>
        <el-descriptions-item label="价格">{{ detailData.price }}</el-descriptions-item>
        <el-descriptions-item label="种类">
          <el-tag :type="typeTag(detailData.type)">{{ typeLabel(detailData.type) }}</el-tag>
        </el-descriptions-item>
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
      :title="isEdit ? '编辑仓库管理' : '新建仓库管理'"
      width="480px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入仓库名称" />
        </el-form-item>
        <el-form-item label="容量" prop="capacity">
          <el-input-number
            v-model="form.capacity"
            :min="0"
            :precision="2"
            style="width: 100%"
            placeholder="仓库容量"
          />
        </el-form-item>
        <el-form-item label="价格" prop="price">
          <el-input-number
            v-model="form.price"
            :min="0"
            :precision="2"
            style="width: 100%"
            placeholder="仓库价格"
          />
        </el-form-item>
        <el-form-item label="种类" prop="type">
          <el-select v-model="form.type" placeholder="选择仓库种类" style="width: 100%">
            <el-option label="原料仓库" value="MATERIAL" />
            <el-option label="零件仓库" value="PART" />
            <el-option label="成品仓库" value="PRODUCT" />
            <el-option label="燃料仓库" value="FUEL" />
          </el-select>
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
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";
import api from "@/api/request";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";

interface Warehouse {
  id: number;
  name: string;
  capacity: number;
  price: number;
  type: string;
  createdAt: string;
  updatedAt: string;
}

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const data = ref<Warehouse[]>([]);
const loading = ref(false);
const searchText = ref("");

const filteredData = computed(() => {
  const list = Array.isArray(data.value) ? data.value : [];
  if (!searchText.value) return list;
  const q = searchText.value.toLowerCase();
  return list.filter((w) => String(w?.name ?? "").toLowerCase().includes(q));
});

const detailVisible = ref(false);
const detailData = ref<Warehouse | null>(null);
function showDetail(row: Warehouse) {
  detailData.value = row;
  detailVisible.value = true;
}

const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref(0);
const submitting = ref(false);
const formRef = ref();

const form = reactive({ name: "", capacity: 0, price: 0, type: "MATERIAL" });
const formRules = {
  name: [{ required: true, message: "请输入仓库名称", trigger: "blur" }],
  capacity: [{ required: true, message: "请输入容量", trigger: "blur" }],
  price: [{ required: true, message: "请输入价格", trigger: "blur" }],
  type: [{ required: true, message: "请选择种类", trigger: "change" }],
};

onMounted(loadData);

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(loadData, () => {
  data.value = [];
});

useResourceChanged("warehouses", () => {
  loadData();
});
async function loadData() {
  loading.value = true;
  try {
    if (!compStore.competitionId) {
      data.value = [];
      loading.value = false;
      return;
    }
    const res = await api.get("/warehouses", {
      params: { competitionId: compStore.competitionId },
    });
    data.value = Array.isArray(res) ? res : [];
  } catch (e) {
    console.error("Failed to load warehouses:", e);
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
  form.capacity = 0;
  form.price = 0;
  form.type = "MATERIAL";
  dialogVisible.value = true;
}
function openEdit(row: Warehouse) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name;
  form.capacity = row.capacity;
  form.price = row.price;
  form.type = row.type;
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
        await api.patch(`/warehouses/${editingId.value}`, body);
        ElMessage.success("已更新");
      } else {
        await api.post("/warehouses", body);
        ElMessage.success("已创建");
      }
      dialogVisible.value = false;
      loadData();
    } catch (e) {
      console.error("Failed to submit warehouse:", e);
    } finally {
      submitting.value = false;
    }
  });
}

async function handleDelete(row: Warehouse) {
  let impact: any = null;
  try {
    impact = await api.get(`/warehouses/${row.id}/impact`, { cache: false });
  } catch {
    impact = null;
  }
  try {
    await confirmDeleteWithImpact(row.name, impact);
    await api.delete(`/warehouses/${row.id}`, {
      params: { competitionId: compStore.competitionId },
    });
    ElMessage.success("已删除");
    loadData();
  } catch (e) {
    console.error("Failed to delete warehouse:", e);
  }
}

function typeLabel(t: string) {
  return { MATERIAL: "原料仓库", PART: "零件仓库", PRODUCT: "成品仓库", FUEL: "燃料仓库" }[t] || t;
}
function typeTag(t: string) {
  return { MATERIAL: "", PART: "success", PRODUCT: "warning", FUEL: "danger" }[t] || "";
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
