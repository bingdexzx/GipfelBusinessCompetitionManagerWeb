<template>
  <div class="vehicles-manager">
    <div class="vm-toolbar">
      <h2 class="vm-title">{{ authStore.can("data:vehicle:edit") ? "载具管理" : "载具" }}</h2>
      <div class="vm-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索载具"
          clearable
          style="width: 200px"
          size="default"
        />
        <el-button v-if="authStore.can('data:vehicle:edit')" type="primary" @click="openCreate"
          >+ 新建</el-button
        >
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table v-loading="loading" :data="filteredData" border stripe style="width: 100%">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="fuelConsumptionPerKm" label="每公里油耗" />
      <el-table-column prop="maxCargo" label="最大载货量" />
      <el-table-column prop="price" label="价格" />
      <el-table-column prop="carbonEmission" label="碳排放系数" />
      <el-table-column
        v-if="authStore.can('data:vehicle:edit')"
        label="操作"
        width="200"
        fixed="right"
      >
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button v-if="authStore.can('data:vehicle:edit')" size="small" @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button
            v-if="authStore.can('data:vehicle:edit')"
            size="small"
            type="danger"
            @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <el-dialog append-to-body v-model="detailVisible" title="载具详情" width="560px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="每公里油耗">{{
          detailData.fuelConsumptionPerKm
        }}</el-descriptions-item>
        <el-descriptions-item label="最大载货量">{{ detailData.maxCargo }}</el-descriptions-item>
        <el-descriptions-item label="价格">{{ (detailData as any).price }}</el-descriptions-item>
        <el-descriptions-item label="碳排放系数">{{
          (detailData as any).carbonEmission
        }}</el-descriptions-item>
        <el-descriptions-item label="燃料">{{
          getFuelName(detailData.fuelId)
        }}</el-descriptions-item>
        <el-descriptions-item label="可通过路径类型">
          <template v-if="detailData.pathTypeIds?.length">
            <el-tag
              v-for="ptId in detailData.pathTypeIds"
              :key="ptId"
              size="small"
              style="margin: 2px"
            >
              {{ getPathTypeNameById(ptId) }}
            </el-tag>
          </template>
          <span v-else style="color: #c0c4cc">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{
          $formatTime((detailData as any).createdAt)
        }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{
          $formatTime((detailData as any).updatedAt)
        }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑载具管理' : '新建载具管理'"
      width="560px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入载具名称" />
        </el-form-item>

        <el-form-item label="燃料" prop="fuelId" required>
          <el-select v-model="form.fuelId" placeholder="选择燃料" filterable style="width: 100%">
            <el-option v-for="f in fuelOptions" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
        </el-form-item>

        <el-form-item label="每公里油耗" prop="fuelConsumptionPerKm">
          <el-input-number
            v-model="form.fuelConsumptionPerKm"
            :min="0"
            :precision="2"
            placeholder="每公里油耗"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="最大载货量" prop="maxCargo">
          <el-input-number
            v-model="form.maxCargo"
            :min="0"
            :precision="2"
            placeholder="最大载货量"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="价格" prop="price">
          <el-input-number
            v-model="form.price"
            :min="0"
            :precision="2"
            placeholder="价格"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="碳排放系数" prop="carbonEmission">
          <el-input-number
            v-model="form.carbonEmission"
            :min="0"
            :precision="4"
            placeholder="碳排放系数"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="可通过路径类型" required>
          <el-select
            v-model="form.pathTypeIds"
            multiple
            filterable
            placeholder="选择路径类型"
            style="width: 100%"
          >
            <el-option
              v-for="pt in pathTypeOptions"
              :key="pt.value"
              :label="pt.label"
              :value="pt.value"
            />
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

interface VehicleItem {
  id: number;
  name: string;
  fuelConsumptionPerKm: number;
  maxCargo?: number;
  fuelId?: number;
  pathTypeIds?: number[];
}

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const data = ref<VehicleItem[]>([]);
const loading = ref(false);
const searchText = ref("");
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref();
const detailVisible = ref(false);
const detailData = ref<VehicleItem | null>(null);

const fuelOptions = ref<{ label: string; value: number }[]>([]);
const pathTypeOptions = ref<{ label: string; value: number }[]>([]);

const form = reactive({
  name: "",
  fuelId: null as number | null,
  fuelConsumptionPerKm: 0,
  maxCargo: 0,
  price: 0,
  carbonEmission: 0,
  pathTypeIds: [] as number[],
});

const formRules = {
  name: [{ required: true, message: "请输入载具名称", trigger: "blur" }],
  fuelConsumptionPerKm: [{ required: true, message: "请输入每公里油耗", trigger: "blur" }],
  maxCargo: [{ required: true, message: "请输入最大载货量", trigger: "blur" }],
  price: [{ required: true, message: "请输入价格", trigger: "blur" }],
  carbonEmission: [{ required: true, message: "请输入碳排放系数", trigger: "blur" }],
};

const filteredData = computed(() => {
  const list = Array.isArray(data.value) ? data.value : [];
  if (!searchText.value) return list;
  const q = searchText.value.toLowerCase();
  return list.filter(
    (item) =>
      String(item?.name ?? "")
        .toLowerCase()
        .includes(q) || String(item?.fuelConsumptionPerKm ?? "").includes(q),
  );
});

onMounted(() => {
  loadData();
  loadFuelOptions();
  loadPathTypeOptions();
});

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(
  () => {
    loadData();
    loadFuelOptions();
    loadPathTypeOptions();
  },
  () => {
    data.value = [];
  },
);

useResourceChanged("vehicles", () => {
  loadData();
});

async function loadData() {
  loading.value = true;
  try {
    if (!compStore.competitionId) {
      data.value = [];
      return;
    }
    const params: any = { page: 1, pageSize: 100, competitionId: compStore.competitionId };
    const res: any = await api.get("/vehicles", { params });
    data.value = Array.isArray(res) ? res : res?.items || [];
  } catch (e) {
    console.error("Failed to load vehicles:", e);
    /* handled by interceptor */
  } finally {
    loading.value = false;
  }
}

async function loadFuelOptions() {
  try {
    const res: any = await api.get("/fuels", {
      params: { page: 1, pageSize: 200, competitionId: compStore.competitionId },
    });
    const items = Array.isArray(res) ? res : res?.items || [];
    fuelOptions.value = items.map((f: any) => ({ label: f.name, value: f.id }));
  } catch {
    /* handled by interceptor */
  }
}

async function loadPathTypeOptions() {
  try {
    const res: any = await api.get("/path-types", {
      params: { competitionId: compStore.competitionId },
    });
    const items = Array.isArray(res) ? res : res?.items || [];
    pathTypeOptions.value = items.map((pt: any) => ({ label: pt.name, value: pt.id }));
  } catch {
    /* handled by interceptor */
  }
}

function showDetail(row: VehicleItem) {
  detailData.value = row;
  detailVisible.value = true;
}

function getFuelName(id: number | null | undefined): string {
  if (!id) return "-";
  const f = fuelOptions.value.find((o) => o.value === id);
  return f?.label || "-";
}

function getPathTypeNameById(id: number): string {
  const pt = pathTypeOptions.value.find((o) => o.value === id);
  return pt?.label || `#${id}`;
}

function openCreate() {
  if (!compStore.competitionId) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editingId.value = null;
  form.name = "";
  form.fuelId = null;
  form.fuelConsumptionPerKm = 0;
  form.maxCargo = 0;
  form.price = 0;
  form.carbonEmission = 0;
  form.pathTypeIds = [];
  dialogVisible.value = true;
}

function openEdit(row: VehicleItem) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name || "";
  form.fuelId = row.fuelId ?? null;
  form.fuelConsumptionPerKm = row.fuelConsumptionPerKm ?? 0;
  form.maxCargo = (row as any).maxCargo ?? 0;
  form.price = (row as any).price ?? 0;
  form.carbonEmission = (row as any).carbonEmission ?? 0;
  form.pathTypeIds = row.pathTypeIds ?? [];
  dialogVisible.value = true;
}

async function handleDelete(row: VehicleItem) {
  let impact: any = null;
  try {
    impact = await api.get(`/vehicles/${row.id}/impact`, { cache: false });
  } catch {
    impact = null;
  }
  try {
    await confirmDeleteWithImpact(row.name ?? `载具#${row.id}`, impact);
    await api.delete(`/vehicles/${row.id}`, {
      params: { competitionId: compStore.competitionId },
    });
    ElMessage.success("已删除");
    loadData();
  } catch (e) {
    console.error("Failed to delete vehicle:", e);
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
      fuelId: form.fuelId,
      fuelConsumptionPerKm: form.fuelConsumptionPerKm,
      maxCargo: form.maxCargo,
      price: form.price,
      carbonEmission: form.carbonEmission,
      pathTypeIds: form.pathTypeIds,
    };
    try {
      if (isEdit.value && editingId.value) {
        await api.patch(`/vehicles/${editingId.value}`, body);
      } else {
        await api.post("/vehicles", body);
      }
      ElMessage.success(isEdit.value ? "已更新" : "已创建");
      dialogVisible.value = false;
      loadData();
    } catch (e) {
      console.error("Failed to submit vehicle:", e);
    } finally {
      submitting.value = false;
    }
  });
}

function resetForm() {
  formRef.value?.resetFields();
  form.pathTypeIds = [];
}
</script>

<style scoped>
.vehicles-manager {
  padding: 0;
}
.vm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.vm-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.vm-actions {
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
