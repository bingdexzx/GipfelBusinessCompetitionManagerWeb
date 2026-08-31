<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { mapsApi } from "@/api";
import { useCompetitionStore } from "@/stores/competition";
import { onResourceChanged } from "@/realtime/resource-changed";

const competition = useCompetitionStore();
const competitionId = computed(() => competition.currentId);
const loading = ref(false);
const data = ref<{ nodes: any[]; edges: any[]; nodeTypes: any[]; pathTypes: any[] }>({
  nodes: [], edges: [], nodeTypes: [], pathTypes: [],
});
const activeTab = ref("nodes");

async function load() {
  if (!competitionId.value) return;
  loading.value = true;
  try {
    const res: any = await mapsApi.full(competitionId.value);
    data.value = {
      nodes: res?.nodes || [],
      edges: res?.edges || [],
      nodeTypes: res?.nodeTypes || [],
      pathTypes: res?.pathTypes || [],
    };
  } catch {
    /* ignore */
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  load();
  onResourceChanged("map-nodes", () => load());
  onResourceChanged("map-edges", () => load());
});

const tabs = [
  { name: "nodes", label: "节点", resource: mapsApi.nodes },
  { name: "edges", label: "连线", resource: mapsApi.edges },
  { name: "nodeTypes", label: "节点类型", resource: mapsApi.nodeTypes },
  { name: "pathTypes", label: "路径类型", resource: mapsApi.pathTypes },
];

function currentList() {
  return data.value[activeTab.value as keyof typeof data.value] || [];
}
</script>

<template>
  <div class="page-container">
    <div class="toolbar">
      <span>地图管理（比赛：{{ competition.current?.name || "未选择" }}）</span>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px">
      完整可视化地图编辑器（vue-konva 画布）遵循原系统设计，此处提供节点/连线/类型的表格管理。
    </el-alert>
    <el-tabs v-model="activeTab">
      <el-tab-pane v-for="t in tabs" :key="t.name" :label="t.label" :name="t.name">
        <el-table :data="currentList()" border v-loading="loading">
          <el-table-column prop="id" label="ID" width="80" />
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="region" label="区域" v-if="t.name === 'nodes'" />
          <el-table-column prop="distance" label="距离" v-if="t.name === 'edges'" />
          <el-table-column prop="color" label="颜色" v-if="t.name === 'nodeTypes' || t.name === 'pathTypes'" />
          <el-table-column label="更新时间">
            <template #default="{ row }">{{ $formatTime(row.updatedAt) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
</style>
