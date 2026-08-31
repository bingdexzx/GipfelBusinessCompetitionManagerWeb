<template>
  <div class="techtree-manager">
    <div class="tt-toolbar">
      <h2 class="tt-title">{{ authStore.can("data:tech:edit") ? "科技树管理" : "科技树" }}</h2>
      <div class="tt-actions">
        <el-button v-if="authStore.can('data:tech:edit')" type="primary" @click="openCreate"
          >+ 新建节点</el-button
        >
        <el-button @click="viewMode = viewMode === 'tree' ? 'table' : 'tree'">
          {{ viewMode === "tree" ? "表格模式" : "可视化模式" }}
        </el-button>
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <div v-if="viewMode === 'tree'" class="tt-tree-container">
      <div ref="panWrapRef" class="tt-pan-wrap">
        <div ref="chartRef" class="tt-chart"></div>
      </div>
      <div v-if="selectedNode" class="tt-tree-info">
        <h4>{{ selectedNode.name }}</h4>
        <div class="tt-info-row">
          <span class="tt-info-label">描述</span>{{ selectedNode.description || "-" }}
        </div>
        <div class="tt-info-row">
          <span class="tt-info-label">层级</span>{{ selectedNode.tier }}
        </div>
        <div class="tt-info-row">
          <span class="tt-info-label">研发费用</span>{{ selectedNode.researchCost ?? 0 }}
        </div>
        <div class="tt-info-row">
          <span class="tt-info-label">前置依赖</span>
          <span v-if="selectedNode.prerequisites?.length">
            {{ selectedNode.prerequisites.map((p: any) => p.prerequisite?.name).join("、") }}
          </span>
          <span v-else style="color: #c0c4cc">无</span>
        </div>
        <div class="tt-info-actions">
          <el-button
            v-if="authStore.can('data:tech:edit')"
            size="small"
            @click="editNode(selectedNode)"
            >编辑</el-button
          >
          <el-button
            v-if="authStore.can('data:tech:edit')"
            size="small"
            type="danger"
            @click="handleDelete(selectedNode)"
            >删除</el-button
          >
        </div>
      </div>
    </div>

    <div v-show="viewMode !== 'tree'">
      <el-table v-loading="loading" :data="nodes" border stripe>
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="description" label="描述" />
        <el-table-column prop="tier" label="层级" />
        <el-table-column prop="researchCost" label="研发费用" />
        <el-table-column label="前置依赖">
          <template #default="{ row }">
            <span v-if="row.prerequisites?.length">
              <el-tag
                v-for="p in row.prerequisites"
                :key="p.prerequisiteNodeId"
                size="small"
                style="margin: 2px"
              >
                {{ p.prerequisite?.name }}
              </el-tag>
            </span>
            <span v-else style="color: #c0c4cc">无</span>
          </template>
        </el-table-column>
        <el-table-column
          v-if="authStore.can('data:tech:edit')"
          label="操作"
          width="220"
          fixed="right"
        >
          <template #default="{ row }">
            <el-button size="small" @click="showDetail(row)">详情</el-button>
            <el-button v-if="authStore.can('data:tech:edit')" size="small" @click="editNode(row)"
              >编辑</el-button
            >
            <el-button
              v-if="authStore.can('data:tech:edit')"
              size="small"
              type="danger"
              @click="handleDelete(row)"
              >删除</el-button
            >
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog append-to-body v-model="detailVisible" title="科技节点详情" width="560px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{
          detailData.description || "-"
        }}</el-descriptions-item>
        <el-descriptions-item label="层级">{{ detailData.tier }}</el-descriptions-item>
        <el-descriptions-item label="研发费用">{{
          detailData.researchCost ?? 0
        }}</el-descriptions-item>
        <el-descriptions-item label="前置依赖">
          <template v-if="detailData.prerequisites?.length">
            <el-tag
              v-for="p in detailData.prerequisites"
              :key="p.prerequisiteNodeId"
              size="small"
              style="margin: 2px"
            >
              {{ p.prerequisite?.name }}
            </el-tag>
          </template>
          <span v-else style="color: #c0c4cc">无</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{
          $formatTime(detailData.createdAt)
        }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{
          $formatTime(detailData.updatedAt)
        }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog append-to-body v-model="showDialog" :title="isEdit ? '编辑节点' : '新建节点'" width="560px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"
          ><el-input v-model="form.description" type="textarea" :rows="2"
        /></el-form-item>
        <el-form-item label="层级"><el-input-number v-model="form.tier" :min="0" /></el-form-item>
        <el-form-item label="研发费用" required
          ><el-input-number v-model="form.researchCost" :min="0" :precision="2" style="width: 100%"
        /></el-form-item>
        <el-form-item label="前置依赖">
          <el-select v-model="form.prerequisiteIds" multiple filterable placeholder="选择前置节点">
            <el-option
              v-for="n in nodes.filter((x) => x.id !== editId)"
              :key="n.id"
              :label="`[T${n.tier}] ${n.name}`"
              :value="n.id"
            />
          </el-select>
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
import { ref, reactive, onMounted, onBeforeUnmount, watch, nextTick } from "vue";
import { useCompetitionStore } from "@/stores/competition";
import { useCompetitionReload } from "@/composables/useCompetitionReload";
import { ElMessage } from "element-plus";
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";
import * as echarts from "echarts";
import api from "@/api/request";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const nodes = ref<any[]>([]);
const loading = ref(false);
const viewMode = ref<"table" | "tree">("tree");
const showDialog = ref(false);
const isEdit = ref(false);
const editId = ref(0);
const submitting = ref(false);
const selectedNode = ref<any>(null);
const detailVisible = ref(false);
const detailData = ref<any>(null);
const chartRef = ref<HTMLDivElement>();
const panWrapRef = ref<HTMLDivElement>();
let chart: echarts.ECharts | null = null;
let resizeHandler: (() => void) | null = null;
let mouseMoveHandler: ((e: MouseEvent) => void) | null = null;
let mouseUpHandler: (() => void) | null = null;
let mouseDownHandler: ((e: MouseEvent) => void) | null = null;
let wheelHandler: ((e: WheelEvent) => void) | null = null;

const form = reactive({
  name: "",
  description: "",
  tier: 0,
  researchCost: 0,
  prerequisiteIds: [] as number[],
});

const formRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  researchCost: [{ required: true, message: "请输入研发费用", trigger: "blur" }],
};

onMounted(loadData);

onBeforeUnmount(() => {
  if (resizeHandler) {
    window.removeEventListener("resize", resizeHandler);
    resizeHandler = null;
  }
  if (mouseMoveHandler) {
    window.removeEventListener("mousemove", mouseMoveHandler);
    mouseMoveHandler = null;
  }
  if (mouseUpHandler) {
    window.removeEventListener("mouseup", mouseUpHandler);
    mouseUpHandler = null;
  }
  const wrap = panWrapRef.value;
  if (mouseDownHandler && wrap) {
    wrap.removeEventListener("mousedown", mouseDownHandler);
    mouseDownHandler = null;
  }
  if (wheelHandler && wrap) {
    wrap.removeEventListener("wheel", wheelHandler);
    wheelHandler = null;
  }
  if (chart) {
    chart.dispose();
    chart = null;
  }
});

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(loadData, () => {
  nodes.value = [];
});

useResourceChanged("tech-nodes", () => {
  loadData();
});

watch(viewMode, async (v) => {
  if (v === "tree") {
    await nextTick();
    if (chart) {
      chart.dispose();
      chart = null;
    }
    renderTree();
  }
});

async function loadData() {
  loading.value = true;
  try {
    if (!compStore.competitionId) {
      nodes.value = [];
      return;
    }
    const res = await api.get("/tech-nodes", {
      params: { competitionId: compStore.competitionId },
    });
    nodes.value = res?.items || res || [];
    await nextTick();
    if (viewMode.value === "tree") renderTree();
  } catch (e) {
    console.error("Failed to load tech nodes:", e);
  } finally {
    loading.value = false;
  }
}

function buildTreeData() {
  const nodeMap = new Map<number, any>();
  for (const n of nodes.value) {
    nodeMap.set(n.id, {
      id: n.id,
      name: `[T${n.tier}] ${n.name}`,
      value: n.name,
      description: n.description,
      tier: n.tier,
      _raw: n,
      children: [] as any[],
    });
  }

  const roots: any[] = [];
  const hasParent = new Set<number>();

  for (const n of nodes.value) {
    const prereqs = n.prerequisites || [];
    for (const p of prereqs) {
      const child = nodeMap.get(n.id);
      const parent = nodeMap.get(p.prerequisiteNodeId);
      if (child && parent) {
        parent.children!.push(child);
        hasParent.add(n.id);
      }
    }
  }

  for (const [id, node] of nodeMap) {
    if (!hasParent.has(id)) roots.push(node);
  }

  if (roots.length === 0 && nodeMap.size > 0) {
    return { name: "科技树", children: Array.from(nodeMap.values()) };
  }

  return roots.length === 1 ? roots[0] : { name: "科技树", children: roots };
}

function buildTreeOpt() {
  return {
    tooltip: { trigger: "item" as const },
    series: [
      {
        type: "tree" as const,
        data: [buildTreeData()],
        orient: "LR" as const,
        symbolSize: 14,
        roam: true,
        scaleLimit: { min: 0.2, max: 5 },
        label: {
          position: "left" as const,
          verticalAlign: "middle" as const,
          align: "right" as const,
          fontSize: 12,
          color: "#1F1F1F",
        },
        leaves: {
          label: {
            position: "right" as const,
            verticalAlign: "middle" as const,
            align: "left" as const,
          },
        },
        lineStyle: { color: "#C0C4CC", width: 2, curveness: 0.5 },
        itemStyle: { color: "#6366f1", borderColor: "#4f46e5" },
        animationDuration: 300,
      },
    ],
  };
}

function renderTree() {
  if (!chartRef.value) return;
  if (chart) {
    chart.dispose();
    chart = null;
  }
  chart = echarts.init(chartRef.value);

  chart.setOption(buildTreeOpt());

  chart.off("click");
  chart.on("click", (params: any) => {
    if (params.data?._raw) {
      selectedNode.value = params.data._raw;
    }
  });

  // Custom pan/zoom on the wrapper — leaves ECharts canvas alone
  const wrap = panWrapRef.value!;
  wrap.style.transformOrigin = "0 0";
  let panning = false,
    panStart: [number, number] = [0, 0];
  let ox = 0,
    oy = 0,
    s = 1;

  // 清理之前的 mousedown 事件监听器
  if (mouseDownHandler) {
    wrap.removeEventListener("mousedown", mouseDownHandler);
  }
  mouseDownHandler = (e: MouseEvent) => {
    if (e.button !== 0) return;
    panning = true;
    panStart = [e.clientX - ox, e.clientY - oy];
  };
  wrap.addEventListener("mousedown", mouseDownHandler);

  const mover = (e: MouseEvent) => {
    if (!panning) return;
    ox = e.clientX - panStart[0];
    oy = e.clientY - panStart[1];
    wrap.style.transform = `translate(${ox}px, ${oy}px) scale(${s})`;
  };
  const uper = () => {
    panning = false;
  };

  // 清理之前的事件监听器
  if (mouseMoveHandler) {
    window.removeEventListener("mousemove", mouseMoveHandler);
  }
  if (mouseUpHandler) {
    window.removeEventListener("mouseup", mouseUpHandler);
  }

  mouseMoveHandler = mover;
  mouseUpHandler = uper;
  window.addEventListener("mousemove", mover);
  window.addEventListener("mouseup", uper);

  // 清理之前的 wheel 事件监听器
  if (wheelHandler) {
    wrap.removeEventListener("wheel", wheelHandler);
  }
  wheelHandler = (e: WheelEvent) => {
    e.preventDefault();
    const r = wrap.parentElement!.getBoundingClientRect();
    const mx = (e.clientX - r.left) / s,
      my = (e.clientY - r.top) / s;
    s = Math.max(0.2, Math.min(5, s * (e.deltaY > 0 ? 0.9 : 1.1)));
    ox = e.clientX - r.left - mx * s;
    oy = e.clientY - r.top - my * s;
    wrap.style.transform = `translate(${ox}px, ${oy}px) scale(${s})`;
  };
  wrap.addEventListener("wheel", wheelHandler, { passive: false });

  // 清理之前的 resize 事件监听器
  if (resizeHandler) {
    window.removeEventListener("resize", resizeHandler);
  }

  resizeHandler = () => chart?.resize();
  window.addEventListener("resize", resizeHandler);
  chart.resize();
}

function showDetail(row: any) {
  detailData.value = row;
  detailVisible.value = true;
}

function openCreate() {
  if (!compStore.competitionId) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editId.value = 0;
  form.name = "";
  form.description = "";
  form.tier = 0;
  form.researchCost = 0;
  form.prerequisiteIds = [];
  showDialog.value = true;
}

function editNode(row: any) {
  isEdit.value = true;
  editId.value = row.id;
  form.name = row.name;
  form.description = row.description || "";
  form.tier = row.tier;
  form.researchCost = row.researchCost || 0;
  form.prerequisiteIds = (row.prerequisites || []).map((p: any) => p.prerequisiteNodeId);
  showDialog.value = true;
}

async function handleSubmit() {
  submitting.value = true;
  try {
    const payload = {
      competitionId: compStore.competitionId,
      name: form.name,
      description: form.description,
      tier: form.tier,
      researchCost: form.researchCost,
      prerequisites: form.prerequisiteIds.map((id) => ({ prerequisiteNodeId: id })),
    };
    if (isEdit.value) {
      await api.patch(`/tech-nodes/${editId.value}`, payload);
    } else {
      await api.post("/tech-nodes", payload);
    }
    ElMessage.success(isEdit.value ? "已更新" : "已创建");
    showDialog.value = false;
    loadData();
  } catch (e) {
    console.error("Failed to submit tech node:", e);
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: any) {
  let impact: any = null;
  try {
    impact = await api.get(`/tech-nodes/${row.id}/impact`, { cache: false });
  } catch {
    impact = null;
  }
  try {
    await confirmDeleteWithImpact(row.name ?? row.id, impact);
    await api.delete(`/tech-nodes/${row.id}`, {
      params: { competitionId: compStore.competitionId },
    });
    ElMessage.success("已删除");
    loadData();
  } catch (e) {
    console.error("Failed to delete tech node:", e);
  }
}
</script>

<style scoped>
.tt-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.tt-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.tt-actions {
  display: flex;
  gap: 8px;
}
.tt-tree-container {
  display: flex;
  gap: 16px;
  height: calc(100vh - 200px);
  overflow: hidden;
}
.tt-chart {
  width: 100%;
  height: 100%;
  min-height: 500px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #fff;
}
.tt-pan-wrap {
  flex: 1;
  overflow: hidden;
  position: relative;
  min-height: 500px;
}
.tt-tree-info {
  width: 260px;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tt-tree-info h4 {
  font-size: 16px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0 0 12px;
}
.tt-info-row {
  font-size: 13px;
  color: #5c5c5c;
  margin-bottom: 6px;
}
.tt-info-label {
  display: inline-block;
  width: 64px;
  color: #8c8c8c;
  font-size: 12px;
}
.tt-info-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
  padding-top: 12px;
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
