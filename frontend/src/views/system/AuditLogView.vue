<template>
  <div class="audit-log">
    <div class="mm-toolbar">
      <h2 class="mm-title">审计日志</h2>
      <div class="mm-actions">
        <el-button :icon="Refresh" @click="reload">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never" class="block-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">操作留痕（共 {{ total }} 条）</span>
          <div class="card-actions filters">
            <el-select v-model="filters.kind" placeholder="类型" clearable style="width: 110px" @change="reload">
              <el-option label="写操作" value="write" />
              <el-option label="异常" value="error" />
            </el-select>
            <el-input
              v-model="filters.model"
              placeholder="模型，如 Company"
              clearable
              style="width: 160px"
              @change="reload"
            />
            <el-input
              v-model="filters.operatorId"
              placeholder="操作人 ID"
              clearable
              style="width: 120px"
              @change="reload"
            />
            <el-input
              v-model="filters.competitionId"
              placeholder="比赛 ID"
              clearable
              style="width: 110px"
              @change="reload"
            />
          </div>
        </div>
      </template>

      <!-- 桌面/平板：表格 -->
      <el-table v-if="!isPhone" :data="items" size="small" v-loading="loading" stripe>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="类型" width="80">
          <template #default="{ row }">
            <el-tag :type="row.kind === 'error' ? 'danger' : 'info'" size="small">
              {{ row.kind === "error" ? "异常" : "写操作" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作人" width="140">
          <template #default="{ row }">{{ row.operatorName || row.operatorId || "-" }}</template>
        </el-table-column>
        <el-table-column prop="action" label="动作" min-width="150" show-overflow-tooltip />
        <el-table-column label="对象" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.model ? `${row.model}#${row.recordId ?? "-"}` : "-" }}
          </template>
        </el-table-column>
        <el-table-column prop="competitionId" label="比赛" width="70" />
        <el-table-column label="概要" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ brief(row) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="showDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 手机：卡片 -->
      <MobileCards
        v-else
        :data="items"
        :columns="mobileColumns"
        :row-key="(row: any) => row.id"
        :loading="loading"
        title-key="action"
      >
        <template #kind="{ row }">
          <el-tag :type="row.kind === 'error' ? 'danger' : 'info'" size="small">
            {{ row.kind === "error" ? "异常" : "写操作" }}
          </el-tag>
        </template>
        <template #brief="{ row }">{{ brief(row) }}</template>
        <template #actions="{ row }">
          <el-button size="small" type="primary" @click="showDetail(row)">详情</el-button>
        </template>
      </MobileCards>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next, total"
          :pager-count="isPhone ? 5 : 9"
          background
          @current-change="load"
        />
      </div>
    </el-card>

    <el-dialog v-model="detailVisible" title="审计详情" width="min(680px, 92vw)">
      <template v-if="detail">
        <el-descriptions :column="isPhone ? 1 : 2" size="small" border>
          <el-descriptions-item label="类型">
            {{ detail.kind === "error" ? "异常" : "写操作" }}
          </el-descriptions-item>
          <el-descriptions-item label="时间">{{ fmtTime(detail.createdAt) }}</el-descriptions-item>
          <el-descriptions-item label="操作人">
            {{ detail.operatorName || "-" }}（ID: {{ detail.operatorId ?? "-" }}）
          </el-descriptions-item>
          <el-descriptions-item label="动作">{{ detail.action }}</el-descriptions-item>
          <el-descriptions-item label="对象">
            {{ detail.model ? `${detail.model}#${detail.recordId ?? "-"}` : "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="比赛 ID">{{ detail.competitionId ?? "-" }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.kind === 'error'" label="状态码">
            {{ detail.statusCode ?? "-" }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.kind === 'error'" label="来源 IP">
            {{ detail.ip || "-" }}
          </el-descriptions-item>
          <el-descriptions-item v-if="detail.requestId" label="请求 ID">
            {{ detail.requestId }}
          </el-descriptions-item>
        </el-descriptions>
        <div v-if="detail.errorSummary" class="detail-block">
          <div class="detail-label">错误摘要</div>
          <pre class="detail-pre">{{ detail.errorSummary }}</pre>
        </div>
        <div v-if="prettyChanges" class="detail-block">
          <div class="detail-label">变更内容（敏感字段已脱敏）</div>
          <pre class="detail-pre">{{ prettyChanges }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { Refresh } from "@element-plus/icons-vue";
import { auditApi } from "@/api";
import type { AuditLog } from "@/types/api";
import { useBreakpoint } from "@/composables/useBreakpoint";
import MobileCards from "@/components/common/MobileCards.vue";

const { isPhone } = useBreakpoint();

const items = ref<AuditLog[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const loading = ref(false);
const filters = reactive({ kind: "", model: "", operatorId: "", competitionId: "" });

const detail = ref<AuditLog | null>(null);
const detailVisible = ref(false);

const mobileColumns = [
  { prop: "kind", label: "类型", slot: "kind" },
  { prop: "operatorName", label: "操作人" },
  { prop: "createdAt", label: "时间", formatter: (row: AuditLog) => fmtTime(row.createdAt) },
  { prop: "brief", label: "概要", slot: "brief" },
];

function fmtTime(v: string): string {
  return v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "-";
}

function brief(row: AuditLog): string {
  if (row.kind === "error") return row.errorSummary || "-";
  if (row.changes) {
    try {
      const keys = Object.keys(JSON.parse(row.changes));
      return keys.length ? `变更字段：${keys.join("、")}` : "-";
    } catch {
      return "-";
    }
  }
  return "-";
}

function showDetail(row: AuditLog) {
  detail.value = row;
  detailVisible.value = true;
}

const prettyChanges = computed(() => {
  const raw = detail.value?.changes;
  if (!raw) return "";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return raw;
  }
});

async function load() {
  loading.value = true;
  try {
    const res: any = await auditApi.list({
      kind: filters.kind || undefined,
      model: filters.model || undefined,
      operatorId: filters.operatorId ? Number(filters.operatorId) : undefined,
      competitionId: filters.competitionId ? Number(filters.competitionId) : undefined,
      page: page.value,
      pageSize,
    });
    items.value = (res?.items ?? []) as AuditLog[];
    total.value = res?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

function reload() {
  page.value = 1;
  load();
}

onMounted(load);
</script>

<style scoped>
.audit-log {
  padding: 16px;
}
.block-card {
  margin-top: 12px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.card-title {
  font-weight: 600;
}
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.detail-block {
  margin-top: 12px;
}
.detail-label {
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  margin-bottom: 4px;
}
.detail-pre {
  margin: 0;
  padding: 10px;
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
}
</style>
