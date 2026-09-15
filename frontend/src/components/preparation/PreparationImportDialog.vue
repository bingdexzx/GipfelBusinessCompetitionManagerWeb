<template>
  <el-dialog
    v-model="visible"
    title="导入比赛准备归档"
    width="860px"
    top="5vh"
    append-to-body
    destroy-on-close
    @open="onOpen"
  >
    <!-- 步骤一：选文件 -->
    <el-steps :active="step" simple class="imp-steps">
      <el-step title="选择归档文件" />
      <el-step title="预览检查" />
      <el-step title="确认导入" />
    </el-steps>

    <div class="imp-body">
      <!-- 文件选择 -->
      <div v-if="step === 0" class="imp-step">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="归档文件来自「比赛准备总览 → 导出 JSON / 导出本组」"
          description="导入只会把文件里包含的数据写入目标比赛；默认先预览（不写库），确认后再真正导入。"
        />
        <el-form label-width="110px" class="imp-form">
          <el-form-item label="目标比赛">
            <span class="imp-target">{{ competitionName || "当前比赛" }}</span>
          </el-form-item>
          <el-form-item label="所属分组">
            <el-select v-model="scope" style="width: 260px">
              <el-option
                v-for="opt in scopeOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
            <span class="imp-hint">仅用于把导入结果归类展示，实际导入以文件内容为准</span>
          </el-form-item>
          <el-form-item label="归档文件">
            <input
              ref="fileInputRef"
              type="file"
              accept=".json,application/json"
              class="imp-file"
              @change="onFileChange"
            />
            <div v-if="fileName" class="imp-file-name">
              已选择：{{ fileName }}（{{ fileSizeText }}）
            </div>
          </el-form-item>
          <el-form-item label="导入选项">
            <el-checkbox v-model="allowNonEmpty">
              允许导入到已有数据的比赛
            </el-checkbox>
            <div class="imp-hint">
              默认只允许导入到「空比赛」；目标比赛已有公司/物资等数据时会被拒绝，需勾选此项。
            </div>
          </el-form-item>
        </el-form>
        <div v-if="parseError" class="imp-error">{{ parseError }}</div>
      </div>

      <!-- 预览与配置 -->
      <div v-else class="imp-step">
        <!-- 导入方式 -->
        <div class="imp-mode">
          <span class="imp-mode-label">导入方式</span>
          <el-radio-group v-model="mode" @change="runPreview">
            <el-radio-button value="append">追加（已存在的保留不动）</el-radio-button>
            <el-radio-button value="overwrite">覆盖（已存在的按归档更新）</el-radio-button>
          </el-radio-group>
          <span class="imp-hint">
            {{
              mode === "append"
                ? "只补目标比赛缺的数据；同名的公司/物资等整块保留，不会改动或重复创建"
                : "同名记录按归档内容更新字段（保留其主键与关联关系）"
            }}
          </span>
        </div>

        <!-- 资源选择 -->
        <div class="imp-res">
          <div class="imp-res-head">
            <span class="imp-res-title">
              导入范围：已选 {{ selectedResources.length }} / {{ resourceRows.length }} 类
            </span>
            <el-button size="small" text @click="selectAll">全选</el-button>
            <el-button size="small" text @click="selectNone">全不选</el-button>
            <el-button size="small" text @click="selectRecommended">
              只选「建议导入」
            </el-button>
            <span class="imp-hint">
              未勾选的资源会原样保留在目标比赛，不受影响
            </span>
          </div>
          <el-table
            :data="resourceRows"
            size="small"
            border
            max-height="200"
            @selection-change="onSelectionChange"
            ref="resTableRef"
          >
            <el-table-column type="selection" width="44" />
            <el-table-column prop="label" label="数据类别" min-width="170" />
            <el-table-column label="归档条数" width="90" align="right">
              <template #default="{ row }">{{ row.count }}</template>
            </el-table-column>
            <el-table-column label="目标已存在" width="100" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.exists" size="small" type="warning">是</el-tag>
                <span v-else class="imp-dim">—</span>
              </template>
            </el-table-column>
            <el-table-column label="建议" width="110" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.recommend" size="small" type="success">
                  {{ mode === "append" ? "可追加" : "可覆盖" }}
                </el-tag>
                <el-tag v-else size="small" type="info">保留</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <template v-if="preview">
          <el-alert
            v-if="preview.blocked"
            type="error"
            :closable="false"
            show-icon
            title="目标比赛已有数据，当前设置下会被拒绝"
            description="请勾选「允许导入到已有数据的比赛」后重新预览，或改用一场空比赛。"
            class="imp-alert"
          />
          <el-alert
            v-else-if="preview.problemCount > 0"
            type="warning"
            :closable="false"
            show-icon
            class="imp-alert"
            :title="`预览完成：新增 ${preview.created} / 更新 ${preview.updated} / 保留 ${preview.kept || 0}，有 ${preview.problemCount} 条问题需注意`"
          />
          <el-alert
            v-else
            type="success"
            :closable="false"
            show-icon
            class="imp-alert"
            :title="`预览通过：新增 ${preview.created} / 更新 ${preview.updated} / 保留 ${preview.kept || 0} / 跳过 ${preview.skipped}`"
          />

          <div class="imp-meta">
            <span>导入方式：{{ preview.modeLabel || modeLabel }}</span>
            <span>源比赛：{{ preview.sourceCompetition?.name || "—" }}</span>
            <span>→ 目标比赛 ID：{{ preview.targetCompetitionId }}</span>
            <span v-if="preview.occupancy?.length">
              目标已有数据：{{ preview.occupancy.map((o) => o.label + " " + o.count).join("、") }}
            </span>
          </div>

          <el-table
            v-if="preview.resources.length"
            :data="preview.resources"
            size="small"
            border
            stripe
            max-height="220"
          >
            <el-table-column prop="label" label="数据类别" min-width="150" />
            <el-table-column prop="created" label="新增" width="80" align="right" />
            <el-table-column prop="updated" label="更新" width="80" align="right" />
            <el-table-column prop="kept" label="保留" width="80" align="right" />
            <el-table-column prop="skipped" label="跳过" width="80" align="right" />
          </el-table>

          <div v-if="preview.problems.length" class="imp-list imp-list-problem">
            <div class="imp-list-title">需要处理的问题（{{ preview.problems.length }}）</div>
            <ul>
              <li v-for="(p, i) in preview.problems" :key="i">{{ p }}</li>
            </ul>
          </div>
          <div v-if="preview.notes && preview.notes.length" class="imp-list">
            <div class="imp-list-title">提示（{{ preview.notes.length }}）</div>
            <ul>
              <li v-for="(n, i) in preview.notes" :key="i">{{ n }}</li>
            </ul>
          </div>
        </template>
        <div v-else-if="loading" class="imp-loading">正在生成预览…</div>
      </div>
    </div>

    <template #footer>
      <template v-if="step === 0">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="loading" :disabled="!payload" @click="runPreview">
          预览检查
        </el-button>
      </template>
      <template v-else>
        <el-button @click="step = 0" :disabled="importing">返回选择文件</el-button>
        <el-button
          type="danger"
          :loading="importing"
          :disabled="!preview || preview.blocked || !selectedResources.length"
          @click="runImport"
        >
          确认导入（{{ mode === "append" ? "追加" : "覆盖" }} {{ selectedResources.length }} 类）
        </el-button>
      </template>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from "vue";
import { ElMessage } from "element-plus";
import type { TableInstance } from "element-plus";
import { preparationApi, getErrorMessage } from "@/api";
import type { PrepImportMode, PrepImportResult, PrepScope, PrepScopeOption } from "@/types/api";

const props = defineProps<{
  modelValue: boolean;
  competitionId?: number | null;
  competitionName?: string;
  scopeOptions: PrepScopeOption[];
  /** 预选分组（从某个分组面板点「导入本组」时传入） */
  initialScope?: PrepScope;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "imported"): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit("update:modelValue", v),
});

interface ResourceRow {
  resource: string;
  label: string;
  count: number;
  /** 目标比赛是否已有该类数据（用于给建议） */
  exists: boolean;
  /** 建议勾选（追加：目标没有 → 可追加；覆盖：始终可覆盖） */
  recommend: boolean;
}

const step = ref(0);
const scope = ref<PrepScope>("all");
const mode = ref<PrepImportMode>("append");
const allowNonEmpty = ref(false);
const fileName = ref("");
const fileSizeText = ref("");
const payload = ref<Record<string, unknown> | null>(null);
const parseError = ref("");
const loading = ref(false);
const importing = ref(false);
const preview = ref<PrepImportResult | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);

// 资源选择
const resourceRows = ref<ResourceRow[]>([]);
const selectedResources = ref<string[]>([]);
const resTableRef = ref<TableInstance | null>(null);

const modeLabel = computed(() =>
  mode.value === "append" ? "追加（已存在的保留不动）" : "覆盖（已存在的按归档更新）",
);

/** 归档里的资源清单 + 建议（依据上次预览的目标占用情况与当前模式）。 */
function rebuildResourceRows(occupancy: { label: string; count: number }[] = []) {
  const res = (payload.value?.resources || {}) as Record<
    string,
    { label?: string; count?: number; rows?: unknown[] }
  >;
  const existingLabels = new Set(occupancy.map((o) => o.label));
  const rows: ResourceRow[] = Object.entries(res).map(([key, block]) => {
    const label = block?.label || key;
    const exists = existingLabels.size ? existingLabels.has(label) : false;
    const recommend = mode.value === "overwrite" ? true : !exists;
    return {
      resource: key,
      label,
      count: block?.count ?? (block?.rows?.length || 0),
      exists,
      recommend,
    };
  });
  rows.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "zh"));
  resourceRows.value = rows;
}

/** 默认勾选：建议导入的资源，同时剔除 count 为 0 的项。 */
function applyDefaultSelection(recommended: boolean) {
  const picks = resourceRows.value
    .filter((r) => r.count > 0 && (!recommended || r.recommend))
    .map((r) => r.resource);
  selectedResources.value = picks;
  nextTick(() => {
    const table = resTableRef.value;
    if (!table) return;
    table.clearSelection();
    for (const row of resourceRows.value) {
      if (picks.includes(row.resource)) table.toggleRowSelection(row, true);
    }
  });
}

function onSelectionChange(rows: ResourceRow[]) {
  selectedResources.value = rows.map((r) => r.resource);
}

function selectAll() {
  const picks = resourceRows.value.filter((r) => r.count > 0).map((r) => r.resource);
  selectedResources.value = picks;
  const table = resTableRef.value;
  if (table) {
    table.clearSelection();
    for (const row of resourceRows.value) if (picks.includes(row.resource)) table.toggleRowSelection(row, true);
  }
}

function selectNone() {
  selectedResources.value = [];
  resTableRef.value?.clearSelection();
}

function selectRecommended() {
  applyDefaultSelection(true);
}

function onOpen() {
  step.value = 0;
  preview.value = null;
  // 从某个分组面板进入时预选该分组
  scope.value = props.initialScope || "all";
  // 默认追加：overwrite 只应在用户明确想要「以归档为准」时使用
  mode.value = "append";
  allowNonEmpty.value = false;
  resourceRows.value = [];
  selectedResources.value = [];
  if (fileInputRef.value) fileInputRef.value.value = "";
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  parseError.value = "";
  payload.value = null;
  preview.value = null;
  resourceRows.value = [];
  selectedResources.value = [];
  if (!file) {
    fileName.value = "";
    return;
  }
  fileName.value = file.name;
  fileSizeText.value = file.size > 1024 * 1024
    ? `${(file.size / 1024 / 1024).toFixed(2)} MB`
    : `${Math.max(1, Math.round(file.size / 1024))} KB`;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const obj = JSON.parse(String(reader.result));
      if (!obj || typeof obj !== "object" || !obj.resources) {
        parseError.value = "该文件不是本系统导出的准备归档（缺少 resources 字段）";
        return;
      }
      payload.value = obj;
      // 还没预览，先按「追加」的建议默认：全部可追加
      rebuildResourceRows([]);
      applyDefaultSelection(true);
    } catch (err) {
      parseError.value = `JSON 解析失败：${(err as Error).message}`;
    }
  };
  reader.onerror = () => {
    parseError.value = "文件读取失败";
  };
  reader.readAsText(file, "utf-8");
}

/** 当前导入配置（随预览与真正导入一起提交）。 */
function currentConfig(dryRun: boolean) {
  return {
    mode: mode.value,
    resources: selectedResources.value,
    dryRun,
    allowNonEmpty: allowNonEmpty.value,
  };
}

async function runPreview() {
  if (!payload.value) return;
  if (!selectedResources.value.length) {
    ElMessage.warning("请至少勾选一类要导入的数据");
    return;
  }
  loading.value = true;
  try {
    const res = (await preparationApi.importArchive(payload.value, {
      scope: scope.value,
      competitionId: props.competitionId ?? null,
      config: currentConfig(true),
    })) as PrepImportResult;
    // 预览结果会带目标比赛占用情况（首次预览通常为空，因为默认拒绝非空比赛）
    rebuildResourceRows(res.occupancy || []);
    // 目标比赛是空的 → 覆盖与追加等价，统一按追加语义展示
    preview.value = res;
    step.value = 1;
  } catch (e) {
    ElMessage.error(getErrorMessage(e));
  } finally {
    loading.value = false;
  }
}

async function runImport() {
  if (!payload.value) return;
  if (!selectedResources.value.length) {
    ElMessage.warning("请至少勾选一类要导入的数据");
    return;
  }
  importing.value = true;
  try {
    const res = (await preparationApi.importArchive(payload.value, {
      scope: scope.value,
      competitionId: props.competitionId ?? null,
      config: currentConfig(false),
    })) as PrepImportResult;
    ElMessage.success(
      `导入完成（${res.modeLabel || modeLabel.value}）：新增 ${res.created} / 更新 ${res.updated} / 保留 ${res.kept || 0}`,
    );
    visible.value = false;
    emit("imported");
  } catch (e) {
    ElMessage.error(getErrorMessage(e));
  } finally {
    importing.value = false;
  }
}
</script>

<style scoped>
.imp-steps {
  margin-bottom: 16px;
}
.imp-body {
  min-height: 220px;
}
.imp-form {
  margin-top: 16px;
}
.imp-target {
  font-weight: 600;
  color: #303133;
}
.imp-hint {
  margin-left: 10px;
  font-size: 12px;
  color: #909399;
}
.imp-file {
  font-size: 13px;
}
.imp-file-name {
  margin-top: 6px;
  font-size: 12px;
  color: #67c23a;
}
.imp-error {
  margin-top: 8px;
  padding: 8px 12px;
  border-radius: 4px;
  background: #fef0f0;
  color: #f56c6c;
  font-size: 13px;
}
.imp-alert {
  margin-bottom: 12px;
}
.imp-mode {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.imp-mode-label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.imp-res {
  margin-bottom: 12px;
}
.imp-res-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.imp-res-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-right: 6px;
}
.imp-dim {
  color: #c0c4cc;
}
.imp-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: #606266;
  margin-bottom: 10px;
}
.imp-list {
  margin-top: 12px;
  font-size: 12px;
  color: #606266;
}
.imp-list-title {
  font-weight: 600;
  margin-bottom: 4px;
}
.imp-list ul {
  margin: 0;
  padding-left: 18px;
  line-height: 1.8;
  max-height: 180px;
  overflow: auto;
}
.imp-list-problem {
  color: #e6a23c;
}
.imp-loading {
  padding: 40px 0;
  text-align: center;
  color: #909399;
}
</style>
