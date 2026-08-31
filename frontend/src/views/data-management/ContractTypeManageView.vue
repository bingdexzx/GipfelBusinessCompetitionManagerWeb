<template>
  <div class="ct-manager">
    <div class="mm-toolbar">
      <h2 class="mm-title">合同类型管理</h2>
      <div class="mm-actions">
        <el-button
          :disabled="!authStore.can('contractType:manage')"
          @click="openSimpleNew"
          >简单新建</el-button
        >
        <el-button
          type="primary"
          :disabled="!authStore.can('contractType:manage')"
          @click="openGraphNew"
          >可视化新建</el-button
        >
        <el-input
          v-model="searchText"
          placeholder="搜索名称 / key"
          clearable
          style="width: 200px"
        />
      </div>
    </div>

    <el-table v-loading="loading" :data="filteredTypes" border stripe style="width: 100%">
      <el-table-column prop="key" label="标识(key)" min-width="220" />
      <el-table-column prop="name" label="名称" min-width="220" />
      <el-table-column label="参与方数" width="100">
        <template #default="{ row }">{{ partyCountOf(row) }}</template>
      </el-table-column>
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-switch
            v-model="row.enabled"
            :disabled="!authStore.can('contractType:manage')"
            @change="() => toggleEnabled(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">配置</el-button>
          <el-button
            size="small"
            :disabled="!authStore.can('contractType:manage')"
            @click="openSimple(row)"
            >简单编辑</el-button
          >
          <el-button
            size="small"
            type="primary"
            :disabled="!authStore.can('contractType:manage')"
            @click="openGraph(row)"
            >可视化编辑</el-button
          >
          <el-button
            size="small"
            type="danger"
            :disabled="!authStore.can('contractType:manage')"
            @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <el-dialog append-to-body
      v-model="showDetail"
      :title="`合同类型配置 · ${detailRow?.name || ''}`"
      width="720px"
    >
      <el-descriptions :column="2" border>
        <el-descriptions-item label="标识">{{ detailRow?.key }}</el-descriptions-item>
        <el-descriptions-item label="参与方数">{{ partyCountOf(detailRow) }}</el-descriptions-item>
        <el-descriptions-item label="启用">{{
          detailRow?.enabled ? "是" : "否"
        }}</el-descriptions-item>
        <el-descriptions-item label="说明" :span="2">{{
          detailRow?.description || "—"
        }}</el-descriptions-item>
      </el-descriptions>

      <el-divider>参与方角色 (partyRoles)</el-divider>
      <pre class="json-box">{{ pretty(detailRow?.partyRoles) }}</pre>

      <el-divider>输入字段 (inputSchema)</el-divider>
      <pre class="json-box">{{ pretty(detailRow?.inputSchema) }}</pre>

      <el-divider>效果定义 (effects)</el-divider>
      <pre class="json-box">{{ pretty(detailRow?.effects) }}</pre>

      <el-divider>前置检查 (conditions)</el-divider>
      <pre class="json-box">{{ prettyJson(detailRow?.conditions) }}</pre>
    </el-dialog>

    <el-dialog append-to-body
      v-model="showGraph"
      :title="graphTarget ? `可视化编辑 · ${graphTarget.name}` : '可视化新建合同类型'"
      fullscreen
      class="ge-dialog"
      :close-on-click-modal="false"
      destroy-on-close
      @closed="onGraphClosed"
    >
      <ContractTypeGraphEditor
        :contract-type="graphTarget"
        @close="showGraph = false"
        @saved="onGraphSaved"
      />
    </el-dialog>

    <!-- 简单模式编辑器 -->
    <el-dialog append-to-body
      v-model="showSimple"
      :title="simpleTarget ? `简单编辑 · ${simpleTarget.name}` : '简单新建合同类型'"
      width="80%"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <SimpleContractTypeEditor
        :contract-type="simpleTarget"
        @cancel="showSimple = false"
        @saved="onSimpleSaved"
      />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { useAuthStore } from "@/stores/auth";
import { contractTypesApi } from "@/api";
import { ElMessage, ElMessageBox } from "element-plus";
import ContractTypeGraphEditor from "@/components/contracts/ContractTypeGraphEditor.vue";
import SimpleContractTypeEditor from "@/components/contracts/simple/SimpleContractTypeEditor.vue";
import { useResourceChanged } from "@/realtime/useResourceChanged";

const authStore = useAuthStore();

const types = ref<any[]>([]);
const loading = ref(false);
const searchText = ref("");
const showDetail = ref(false);
const detailRow = ref<any>(null);
const showGraph = ref(false);
const graphTarget = ref<any>(null);
const showSimple = ref(false);
const simpleTarget = ref<any>(null);

const filteredTypes = computed(() => {
  if (!searchText.value) return types.value;
  const q = searchText.value.toLowerCase();
  return types.value.filter(
    (t: any) => t.name?.toLowerCase().includes(q) || t.key?.toLowerCase().includes(q),
  );
});

function parseJson(raw: any, fallback: any = []) {
  if (!raw) return fallback;
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw);
    } catch {
      return fallback;
    }
  }
  return raw;
}
// 参与方数：直接取可视化编辑器中的参与方节点数（partyRoles 数组长度），
// 而非后端独立存储的 partyCount 字段，确保与管理界面所见一致。
function partyCountOf(row: any): number {
  const roles = parseJson(row?.partyRoles, []);
  return Array.isArray(roles) ? roles.length : 0;
}
function pretty(raw: any) {
  try {
    return JSON.stringify(parseJson(raw), null, 2);
  } catch {
    return String(raw);
  }
}
// 后端 conditions 已是 JSON 字符串，直接解析后美化
function prettyJson(raw: any) {
  try {
    const v = typeof raw === "string" ? JSON.parse(raw) : raw;
    return JSON.stringify(v ?? [], null, 2);
  } catch {
    return String(raw ?? "[]");
  }
}

async function load() {
  loading.value = true;
  try {
    const res = await contractTypesApi.list(false);
    types.value = Array.isArray(res) ? res : res.items || [];
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}

function openDetail(row: any) {
  detailRow.value = row;
  showDetail.value = true;
}

function openGraph(row: any) {
  graphTarget.value = row;
  showGraph.value = true;
}
function openGraphNew() {
  graphTarget.value = null;
  showGraph.value = true;
}
function onGraphSaved() {
  showGraph.value = false;
  load();
}
function onGraphClosed() {
  graphTarget.value = null;
}

function openSimpleNew() {
  simpleTarget.value = null;
  showSimple.value = true;
}

function openSimple(row: any) {
  simpleTarget.value = row;
  showSimple.value = true;
}

async function onSimpleSaved(data: any) {
  try {
    if (simpleTarget.value) {
      await contractTypesApi.update(simpleTarget.value.id, data);
      ElMessage.success("已更新");
    } else {
      await contractTypesApi.create(data);
      ElMessage.success("已创建");
    }
    showSimple.value = false;
    load();
  } catch (e) {
    console.error(e);
  }
}

async function toggleEnabled(row: any) {
  if (!authStore.can("contractType:manage")) return;
  try {
    await contractTypesApi.update(row.id, { enabled: row.enabled });
    ElMessage.success("已更新启用状态");
  } catch (e) {
    row.enabled = !row.enabled;
    console.error(e);
  }
}

async function handleDelete(row: any) {
  if (!authStore.can("contractType:manage")) return;
  await ElMessageBox.confirm(
    `确定删除合同类型「${row.name}」吗？已基于该类型创建的实例不受影响。`,
    { type: "warning" },
  );
  try {
    await contractTypesApi.remove(row.id);
    ElMessage.success("已删除");
    load();
  } catch (e) {
    console.error(e);
  }
}

onMounted(load);

useResourceChanged("contract-types", () => {
  load();
}, { scope: "global" });
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
.json-box {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>

<!--
  注意：这里必须用非 scoped 样式。
  el-dialog 的 class 属性会落在 .el-dialog 元素自身上，
  写成 `.ge-dialog :deep(.el-dialog)` 是后代选择器，永远匹配不到 → 之前全屏后编辑区高度塌陷。
-->
<style>
.el-dialog.ge-dialog {
  display: flex;
  flex-direction: column;
  margin: 0 !important;
  padding: 0;
  width: 100%;
  height: 100%;
  max-height: 100%;
  border-radius: 0;
  overflow: hidden;
}
.el-dialog.ge-dialog > .el-dialog__header {
  flex: 0 0 auto;
  margin: 0;
  padding: 10px 16px;
  border-bottom: 1px solid #e4e7ed;
}
.el-dialog.ge-dialog > .el-dialog__body {
  flex: 1 1 auto;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}
.el-dialog.ge-dialog > .el-dialog__body > * {
  height: 100%;
}
</style>
