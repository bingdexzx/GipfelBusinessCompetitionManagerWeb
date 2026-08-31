<template>
  <div class="parts-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ authStore.can("data:part:edit") ? "零件管理" : "零件" }}</h2>
      <div class="pm-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索零件"
          clearable
          style="width: 200px"
          size="default"
        />
        <el-button v-if="authStore.can('data:part:edit')" type="primary" @click="openCreate"
          >+ 新建</el-button
        >
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table v-loading="loading" :data="filteredData" border stripe style="width: 100%">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="原料配比" min-width="200">
        <template #default="{ row }">
          <span v-if="!row._materials?.length && !row.partMaterials?.length" style="color: #c0c4cc"
            >-</span
          >
          <el-tag
            v-for="pm in row.partMaterials || row._materials || []"
            :key="pm.id || pm.materialId"
            size="small"
            style="margin: 2px"
          >
            {{ pm.material?.name || pm.materialName }}x{{ pm.ratio }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        v-if="authStore.can('data:part:edit')"
        label="操作"
        width="200"
        fixed="right"
      >
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button v-if="authStore.can('data:part:edit')" size="small" @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button
            v-if="authStore.can('data:part:edit')"
            size="small"
            type="danger"
            @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <el-dialog append-to-body v-model="detailVisible" title="零件详情" width="560px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="原料配比">
          <span
            v-if="!detailData.partMaterials?.length && !detailData._materials?.length"
            style="color: #c0c4cc"
            >无</span
          >
          <el-tag
            v-for="pm in detailData.partMaterials || detailData._materials || []"
            :key="pm.id || pm.materialId"
            size="small"
            style="margin: 2px"
          >
            {{ pm.material?.name || pm.materialName }}x{{ pm.ratio }}
          </el-tag>
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
      :title="isEdit ? '编辑零件管理' : '新建零件管理'"
      width="640px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入零件名称" />
        </el-form-item>

        <el-form-item label="原料配比" prop="partMaterials">
          <div class="sub-table-wrap">
            <div class="sub-table-header">
              <span class="sub-table-col" style="flex: 1">原料</span>
              <span class="sub-table-col" style="width: 140px">比率</span>
              <span class="sub-table-col" style="width: 60px">操作</span>
            </div>
            <div v-for="(item, idx) in form.partMaterials" :key="idx" class="sub-table-row">
              <el-select
                v-model="item.materialId"
                placeholder="选择原料"
                filterable
                style="flex: 1"
                size="default"
              >
                <el-option
                  v-for="m in materialOptions"
                  :key="m.value"
                  :label="m.label"
                  :value="m.value"
                />
              </el-select>
              <el-input-number
                v-model="item.ratio"
                :min="0"
                :precision="2"
                placeholder="比率"
                style="width: 130px"
                size="default"
              />
              <el-button
                type="danger"
                :icon="Delete"
                circle
                size="small"
                style="margin-left: 8px"
                @click="removeMaterial(idx)"
              />
            </div>
          </div>
          <el-button type="primary" plain size="small" style="margin-top: 8px" @click="addMaterial">
            添加原料
          </el-button>
        </el-form-item>

        <el-form-item label="科技需求">
          <el-select
            v-model="form.techRequirements"
            multiple
            filterable
            placeholder="选择科技节点"
            style="width: 100%"
          >
            <el-option v-for="t in techOptions" :key="t.value" :label="t.label" :value="t.value" />
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
import { Delete } from "@element-plus/icons-vue";
import api from "@/api/request";
import { partsApi } from "@/api";
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";

interface MaterialRow {
  materialId: number | null;
  ratio: number;
}

interface PartItem {
  id: number;
  name: string;
  partMaterials?: {
    id?: number;
    materialId: number;
    ratio: number;
    material?: { id: number; name: string };
    materialName?: string;
  }[];
  _materials?: {
    id?: number;
    materialId: number;
    ratio: number;
    material?: { id: number; name: string };
    materialName?: string;
  }[];
  techRequirements?: { techNodeId: number }[];
  createdAt?: string;
  updatedAt?: string;
}

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const data = ref<PartItem[]>([]);
const loading = ref(false);
const searchText = ref("");
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref();
const detailVisible = ref(false);
const detailData = ref<PartItem | null>(null);

const materialOptions = ref<{ label: string; value: number }[]>([]);
const techOptions = ref<{ label: string; value: number }[]>([]);

const form = reactive({
  name: "",
  partMaterials: [] as MaterialRow[],
  techRequirements: [] as number[],
});

const formRules = {
  name: [{ required: true, message: "请输入零件名称", trigger: "blur" }],
  partMaterials: [
    {
      required: true,
      validator: (_rule: any, _value: any, callback: any) => {
        const has = form.partMaterials.some((pm) => pm.materialId && pm.ratio > 0);
        has ? callback() : callback(new Error("请至少添加一项原料配比（选择原料且比率>0）"));
      },
      trigger: "change",
    },
  ],
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

onMounted(() => {
  loadData();
  loadMaterialOptions();
  loadTechOptions();
});

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(
  () => {
    loadData();
    loadMaterialOptions();
    loadTechOptions();
  },
  () => {
    data.value = [];
  },
);

useResourceChanged("parts", () => {
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
    const res: any = await api.get("/parts", { params });
    data.value = Array.isArray(res) ? res : res?.items || [];
  } catch (e) {
    console.error("Failed to load parts:", e);
    /* handled by interceptor */
  } finally {
    loading.value = false;
  }
}

async function loadMaterialOptions() {
  try {
    const res: any = await api.get("/materials", { params: { page: 1, pageSize: 200 } });
    const items = Array.isArray(res) ? res : res?.items || [];
    materialOptions.value = items.map((m: any) => ({ label: m.name, value: m.id }));
  } catch {
    /* handled by interceptor */
  }
}

async function loadTechOptions() {
  try {
    const res: any = await api.get("/tech-nodes", { params: { page: 1, pageSize: 200 } });
    const items = Array.isArray(res) ? res : res?.items || [];
    techOptions.value = items.map((t: any) => ({ label: t.name, value: t.id }));
  } catch {
    /* handled by interceptor */
  }
}

function showDetail(row: PartItem) {
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
  form.partMaterials = [];
  form.techRequirements = [];
  dialogVisible.value = true;
}

function openEdit(row: PartItem) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name || "";
  form.partMaterials = (row.partMaterials || []).map((pm: any) => ({
    materialId: pm.materialId ?? pm.material?.id ?? null,
    ratio: pm.ratio ?? 0,
  }));
  form.techRequirements = (row.techRequirements || []).map((tr: any) => tr.techNodeId ?? tr.id);
  dialogVisible.value = true;
}

function addMaterial() {
  form.partMaterials.push({ materialId: null, ratio: 0 });
  formRef.value?.validateField("partMaterials");
}

function removeMaterial(idx: number) {
  form.partMaterials.splice(idx, 1);
  formRef.value?.validateField("partMaterials");
}

async function handleDelete(row: PartItem) {
  let impact: any = null;
  try {
    impact = await partsApi.impact(row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除，按普通删除提示处理
  }
  await confirmDeleteWithImpact(row.name, impact, {
    baseMessage: "确定删除该零件吗？此操作不可恢复。删除后将一并清除其配比与科技需求关联。",
  });
  try {
    await partsApi.remove(row.id, compStore.competitionId);
    ElMessage.success("已删除");
    loadData();
  } catch (e) {
    console.error("Failed to delete part:", e);
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
      partMaterials: form.partMaterials.map((pm) => ({
        materialId: pm.materialId,
        ratio: pm.ratio,
      })),
      techRequirements: form.techRequirements.map((id) => ({ techNodeId: id })),
    };
    try {
      if (isEdit.value && editingId.value) {
        await api.patch(`/parts/${editingId.value}`, body);
      } else {
        await api.post("/parts", body);
      }
      ElMessage.success(isEdit.value ? "已更新" : "已创建");
      dialogVisible.value = false;
      loadData();
    } catch (e) {
      console.error("Failed to submit part:", e);
    } finally {
      submitting.value = false;
    }
  });
}

function resetForm() {
  formRef.value?.resetFields();
  form.partMaterials = [];
  form.techRequirements = [];
}
</script>

<style scoped>
.parts-manager {
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
.sub-table-wrap {
  width: 100%;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}
.sub-table-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: #f5f7fa;
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}
.sub-table-col {
  padding: 0 4px;
}
.sub-table-row {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-top: 1px solid #ebeef5;
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
