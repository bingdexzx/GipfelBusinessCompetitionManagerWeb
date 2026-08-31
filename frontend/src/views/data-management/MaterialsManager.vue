<template>
  <div class="materials-manager">
    <div class="mm-toolbar">
      <h2 class="mm-title">{{ authStore.can("data:material:edit") ? "原料管理" : "原料" }}</h2>
      <div class="mm-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索原料"
          clearable
          style="width: 200px"
          size="default"
        />
        <el-button v-if="authStore.can('data:material:edit')" type="primary" @click="openCreate"
          >+ 新建</el-button
        >
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table v-loading="loading" :data="filteredMaterials" border stripe style="width: 100%">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="origin" label="产地" :formatter="originFmt" />
      <el-table-column label="价格（按地点）" min-width="220">
        <template #default="{ row }">
          <div v-if="!getRowNodePrices(row).length" class="np-none">—</div>
          <div v-for="p in getRowNodePrices(row)" :key="p.nodeId" class="np-line">
            <span class="np-name">{{ p.nodeName }}</span>
            <span class="np-val">{{ p.price }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="carbonEmissionCoefficient" label="碳排放系数" />
      <el-table-column label="类型">
        <template #default="{ row }">
          <el-tag :type="row.type === 'SPECIAL' ? 'danger' : ''">{{
            row.type === "SPECIAL" ? "特殊原料" : "普通原料"
          }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column
        v-if="authStore.can('data:material:edit')"
        label="操作"
        width="200"
        fixed="right"
      >
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button v-if="authStore.can('data:material:edit')" size="small" @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button
            v-if="authStore.can('data:material:edit')"
            size="small"
            type="danger"
            @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <el-dialog append-to-body v-model="showDetail" title="原料详情" width="480px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="名称">{{ detailRow?.name }}</el-descriptions-item>
        <el-descriptions-item label="产地">{{ formatOrigin(detailRow?.origin) }}</el-descriptions-item>
        <el-descriptions-item label="碳排放系数">{{
          detailRow?.carbonEmissionCoefficient
        }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{
          detailRow?.type === "SPECIAL" ? "特殊原料" : "普通原料"
        }}</el-descriptions-item>
        <el-descriptions-item label="价格">
          <span v-if="!getRowNodePrices(detailRow).length">（无按地点价格）</span>
          <ul v-else class="np-detail">
            <li v-for="p in getRowNodePrices(detailRow)" :key="p.nodeId">
              {{ p.nodeName }}：{{ p.price }}
            </li>
          </ul>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{
          $formatTime(detailRow?.createdAt)
        }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{
          $formatTime(detailRow?.updatedAt)
        }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog append-to-body v-model="showDialog" :title="isEdit ? '编辑原料' : '新建原料'" width="520px">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px">
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="产地" prop="origin">
          <el-select
            v-model="form.origin"
            class="origin-select"
            multiple
            filterable
            placeholder="选择地图节点（可多选）"
            style="width: 100%"
          >
            <el-option
              v-for="node in mapNodes"
              :key="node.id"
              :label="`${node.name} (${node.region})`"
              :value="node.name"
            />
          </el-select>
          <div class="origin-hint">未选择产地表示任何节点都没有这种原料，无需填写价格。</div>
        </el-form-item>
        <el-form-item label="碳排放系数" required
          ><el-input-number
            v-model="form.carbonEmissionCoefficient"
            :min="0"
            :precision="2"
            style="width: 100%"
        /></el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="普通原料" value="NORMAL" />
            <el-option label="特殊原料" value="SPECIAL" />
          </el-select>
        </el-form-item>
        <el-form-item label="价格" required>
          <template v-if="hasOrigin">
            <div class="np-editor">
              <div v-if="!originNodes.length" class="np-empty">（所选产地未匹配到地图节点）</div>
              <div v-for="node in originNodes" :key="node.id" class="np-row">
                <span class="np-label">{{ node.name }}<small>（{{ node.region }}）</small></span>
                <el-input-number
                  :model-value="form.nodePrices[node.id] ?? 0"
                  :min="0"
                  :controls="false"
                  size="small"
                  style="width: 120px"
                  @update:model-value="(v: number | undefined) => onNodePriceChange(node.id, v)"
                />
              </div>
            </div>
            <div class="np-hint">为选中的产地节点分别填写原料价格；计算「原料总价格」时按参与方所在地节点取对应价。</div>
          </template>
          <div v-else class="price-hint">请先在上方选择产地（节点），才会显示对应节点的价格输入框。</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from "vue";
import { useCompetitionStore } from "@/stores/competition";
import { useCompetitionReload } from "@/composables/useCompetitionReload";
import { ElMessage } from "element-plus";
import api from "@/api/request";
import { materialsApi } from "@/api";
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const materials = ref<any[]>([]);
const mapNodes = ref<any[]>([]);
const loading = ref(false);
const searchText = ref("");

const filteredMaterials = computed(() => {
  if (!searchText.value) return materials.value;
  const q = searchText.value.toLowerCase();
  return materials.value.filter(
    (m: any) =>
      m.name?.toLowerCase().includes(q) ||
      formatOrigin(m.origin).toLowerCase().includes(q),
  );
});
const showDialog = ref(false);
const showDetail = ref(false);
const detailRow = ref<any>(null);
const isEdit = ref(false);
const editId = ref(0);
const submitting = ref(false);

// 解析某行原料的按地点价格，关联地图节点名称展示：左节点名、右价格。
function getRowNodePrices(row: any) {
  const raw = row?.nodePrices;
  if (!raw) return [];
  let parsed: Record<string, number> = {};
  try {
    const p = JSON.parse(raw);
    if (p && typeof p === "object" && !Array.isArray(p)) parsed = p;
  } catch {
    return [];
  }
  const nodeNameById = new Map((mapNodes.value || []).map((n: any) => [n.id, n.name]));
  return Object.entries(parsed)
    .filter(([, v]) => typeof v === "number")
    .map(([k, v]) => ({ nodeId: Number(k), price: v, nodeName: nodeNameById.get(Number(k)) || `节点#${k}` }));
}

const formRef = ref();
const formRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  origin: [
    {
      required: true,
      type: "array",
      message: "请选择产地",
      trigger: "change",
    },
  ],
};

const form = reactive({
  name: "",
  origin: [] as string[],
  carbonEmissionCoefficient: 0,
  type: "NORMAL",
  nodePrices: {} as Record<number, number>,
});

// 只有选择了产地（节点），该原料才存在于节点上，才允许填写价格。
const hasOrigin = computed(() => (form.origin?.length ?? 0) > 0);

// 产地清空时，价格与按地点价格失去意义，同步清空，避免存下"无产地却有价"的脏数据。
watch(
  () => form.origin,
  (val) => {
    if (!val || val.length === 0) {
      form.nodePrices = {};
    }
  },
);

// 价格（按地点）只针对选中的产地节点展示输入框，而非全部地图节点。
const originNodes = computed(() =>
  (mapNodes.value || []).filter((n: any) => (form.origin || []).includes(n.name)),
);

// 产地可多选：存储为 JSON 数组字符串（如 ["北京","上海"]），
// 兼容旧的单字符串产地与未设置（undefined/空）。
function formatOrigin(origin: any): string {
  if (!origin) return "—";
  let arr: any = origin;
  if (typeof origin === "string") {
    try {
      const p = JSON.parse(origin);
      arr = Array.isArray(p) ? p : [origin];
    } catch {
      arr = [origin];
    }
  }
  if (Array.isArray(arr)) return arr.length ? arr.join("、") : "—";
  return String(origin);
}

function originFmt(_row: any, _col: any, val: any): string {
  return formatOrigin(val);
}

function parseOriginToArray(origin: any): string[] {
  if (!origin) return [];
  if (Array.isArray(origin)) return origin.map(String);
  if (typeof origin === "string") {
    const s = origin.trim();
    if (!s) return [];
    try {
      const p = JSON.parse(s);
      if (Array.isArray(p)) return p.map(String);
      return [s];
    } catch {
      return [s];
    }
  }
  return [];
}

async function loadMaterials() {
  if (!compStore.competitionId) return;
  try {
    const res = await api.get("/materials", {
      params: { competitionId: compStore.competitionId },
    });
    materials.value = res?.items || res || [];
  } catch (e) {
    console.error("Failed to load materials:", e);
  }
}

async function loadMapNodes() {
  try {
    const res = await api.get("/map-nodes", {
      params: compStore.competitionId ? { competitionId: compStore.competitionId } : {},
    });
    mapNodes.value = res?.items || res || [];
  } catch (e) {
    console.error("Failed to load map nodes:", e);
  }
}

async function reloadAll() {
  loading.value = true;
  try {
    await loadMaterials();
    await loadMapNodes();
  } finally {
    loading.value = false;
  }
}

onMounted(reloadAll);

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(reloadAll, () => {
  materials.value = [];
  mapNodes.value = [];
});

useResourceChanged("materials", () => {
  loadMaterials();
});

function openDetail(row: any) {
  detailRow.value = row;
  showDetail.value = true;
}

function onNodePriceChange(nodeId: number, v: number | undefined) {
  if (v == null || v <= 0) {
    delete (form.nodePrices as Record<number, number>)[nodeId];
  } else {
    (form.nodePrices as Record<number, number>)[nodeId] = v;
  }
}

function openCreate() {
  if (!compStore.competitionId) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editId.value = 0;
  form.name = "";
  form.origin = [];
  form.carbonEmissionCoefficient = 0;
  form.type = "NORMAL";
  form.nodePrices = {};
  showDialog.value = true;
}

function openEdit(row: any) {
  isEdit.value = true;
  editId.value = row.id;
  form.name = row.name;
  form.origin = parseOriginToArray(row.origin);
  form.carbonEmissionCoefficient = row.carbonEmissionCoefficient;
  form.type = row.type || "NORMAL";
  let np: Record<number, number> = {};
  if (row.nodePrices) {
    try {
      const parsed = JSON.parse(row.nodePrices);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        for (const [k, v] of Object.entries(parsed)) {
          if (typeof v === "number") np[Number(k)] = v;
        }
      }
    } catch {
      np = {};
    }
  }
  form.nodePrices = np;
  showDialog.value = true;
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;

  submitting.value = true;
  try {
    const payload = {
      ...form,
      competitionId: compStore.competitionId,
      origin: JSON.stringify(form.origin || []),
      nodePrices: hasOrigin.value ? JSON.stringify(form.nodePrices || {}) : "{}",
    };
    if (isEdit.value) {
      await api.patch(`/materials/${editId.value}`, payload);
    } else {
      await api.post("/materials", payload);
    }
    ElMessage.success(isEdit.value ? "已更新" : "已创建");
    showDialog.value = false;
    const res = await api.get("/materials", {
      params: { competitionId: compStore.competitionId },
    });
    materials.value = res?.items || res || [];
  } catch (e) {
    console.error("Failed to submit material:", e);
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: any) {
  let impact: any = null;
  try {
    impact = await materialsApi.impact(row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除，按普通删除提示处理
  }
  await confirmDeleteWithImpact(row.name, impact, {
    baseMessage: `确定删除 "${row.name}" 吗？此操作不可恢复。删除后将一并清除其零件配比关联。`,
  });
  try {
    await materialsApi.remove(row.id, compStore.competitionId);
    ElMessage.success("已删除");
    const res = await api.get("/materials", {
      params: { competitionId: compStore.competitionId },
    });
    materials.value = res?.items || res || [];
  } catch (e) {
    console.error("Failed to delete material:", e);
  }
}
</script>

<style scoped>
.mm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.mm-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.mm-actions {
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
.np-editor {
  width: 100%;
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  padding: 6px 8px;
}
/* 产地多选框：取消折叠，让所有已选节点名都能显示（可滚动查看） */
.origin-select :deep(.el-select__wrapper) {
  min-height: 40px;
  align-items: flex-start;
  padding-top: 4px;
  padding-bottom: 4px;
}
.origin-select :deep(.el-select__tags) {
  flex-wrap: wrap;
  max-height: 120px;
  overflow-y: auto;
}
.origin-hint,
.price-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin-top: 4px;
}
.price-hint {
  color: #c4564d;
}
.np-empty {
  font-size: 12px;
  color: #909399;
}
.np-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 0;
}
.np-label {
  font-size: 13px;
  color: #303133;
}
.np-label small {
  color: #909399;
  margin-left: 4px;
}
.np-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin-top: 4px;
}
.np-detail {
  margin: 0;
  padding-left: 18px;
}
/* 列表「价格（按地点）」列：左节点名、右价格，逐地点平铺展示 */
.np-none {
  color: #c0c4cc;
}
.np-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 0;
  line-height: 1.4;
}
.np-name {
  font-size: 13px;
  color: #303133;
  text-align: left;
}
.np-val {
  font-size: 13px;
  color: #303133;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
