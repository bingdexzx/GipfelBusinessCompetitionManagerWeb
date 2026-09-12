<template>
  <el-dialog
    v-model="visible"
    title="比赛准备总览"
    width="92%"
    top="4vh"
    append-to-body
    destroy-on-close
    class="prep-dialog"
    @open="onOpen"
  >
    <!-- 顶部：比赛信息 + 汇总 + 导出按钮 -->
    <div class="prep-head">
      <div class="prep-head-left">
        <div class="prep-comp">
          <span class="prep-comp-label">比赛</span>
          <span class="prep-comp-name">{{ plan?.competition?.name || "—" }}</span>
          <el-tag size="small" :type="plan?.competition?.status === 'ACTIVE' ? 'success' : 'danger'">
            {{ plan?.competition?.status === "ACTIVE" ? "进行中" : plan?.competition?.status || "—" }}
          </el-tag>
        </div>
        <div v-if="plan" class="prep-meta">
          生成时间 {{ plan.generatedAt }}　·　准备事项 {{ summary.total }} 项（开赛前必须完成
          {{ summary.required }} 项）
        </div>
      </div>
      <div class="prep-head-right">
        <el-select
          v-model="scope"
          size="small"
          class="prep-scope-select"
          title="选择「导出本组 / 导入本组」作用的分组"
        >
          <el-option
            v-for="opt in scopeOptions"
            :key="opt.value"
            :label="opt.label"
            :value="opt.value"
          />
        </el-select>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
        <el-button
          size="small"
          type="primary"
          :loading="exporting === 'archive'"
          :disabled="!plan"
          @click="handleExportArchive(scope)"
        >
          导出本组
        </el-button>
        <el-button size="small" :disabled="!plan" @click="openImport(scope)">导入本组</el-button>
        <el-divider direction="vertical" />
        <el-button
          size="small"
          :loading="exporting === 'markdown'"
          :disabled="!plan"
          @click="handleExport('markdown')"
        >
          导出 Markdown
        </el-button>
        <el-button
          size="small"
          :loading="exporting === 'json'"
          :disabled="!plan"
          @click="handleExport('json')"
        >
          导出全部 JSON
        </el-button>
      </div>
    </div>

    <!-- 汇总统计卡 -->
    <div v-if="plan" class="prep-summary">
      <div class="prep-sum-card prep-sum-ready">
        <div class="prep-sum-num">{{ summary.ready }}</div>
        <div class="prep-sum-label">就绪</div>
      </div>
      <div class="prep-sum-card prep-sum-warn">
        <div class="prep-sum-num">{{ summary.warning }}</div>
        <div class="prep-sum-label">提醒</div>
      </div>
      <div class="prep-sum-card prep-sum-empty">
        <div class="prep-sum-num">{{ summary.empty }}</div>
        <div class="prep-sum-label">待准备</div>
      </div>
      <div class="prep-sum-card">
        <div class="prep-sum-num">{{ summary.warningCount }}</div>
        <div class="prep-sum-label">提醒条目</div>
      </div>
      <div class="prep-sum-card">
        <div class="prep-sum-num">{{ summary.requiredWarning }}</div>
        <div class="prep-sum-label">必做项含提醒</div>
      </div>
      <div class="prep-sum-card">
        <div class="prep-sum-num">{{ summary.requiredEmpty }}</div>
        <div class="prep-sum-label">必做项待准备</div>
      </div>
    </div>

    <el-alert
      v-if="plan && summary.warningCount > 0"
      type="warning"
      :closable="false"
      show-icon
      class="prep-alert"
      :title="`开赛前建议处理完这 ${summary.warningCount} 条提醒`"
      description="提醒不会阻止任何操作，但多数对应开赛后难以补救的配置问题（如计算字段未配计算图、地图孤立节点、账号无公司范围）。"
    />
    <el-alert
      v-else-if="plan"
      type="success"
      :closable="false"
      show-icon
      class="prep-alert"
      title="全部准备事项均无提醒"
      description="可以导出归档并开始财年。"
    />

    <!-- 分组折叠面板 -->
    <el-collapse v-if="plan" v-model="activeGroups" class="prep-collapse">
      <el-collapse-item
        v-for="cat in plan.categories"
        :key="cat.key"
        :name="cat.key"
      >
        <template #title>
          <div class="prep-cat-title">
            <span class="prep-cat-name">{{ cat.title }}</span>
            <el-tag v-if="cat.summary.ready" size="small" type="success">就绪 {{ cat.summary.ready }}</el-tag>
            <el-tag v-if="cat.summary.warning" size="small" type="warning">提醒 {{ cat.summary.warning }}</el-tag>
            <el-tag v-if="cat.summary.empty" size="small" type="info">待准备 {{ cat.summary.empty }}</el-tag>
            <!-- 分组级导出/导入：只处理本分组的数据 -->
            <span class="prep-cat-actions" @click.stop>
              <el-button
                size="small"
                text
                type="primary"
                :loading="exporting === cat.key"
                @click.stop="handleExportArchive(cat.key)"
              >
                导出本组
              </el-button>
              <el-button size="small" text @click.stop="openImport(cat.key)">导入本组</el-button>
            </span>
          </div>
        </template>

        <div class="prep-cat-desc">{{ cat.description }}</div>

        <div v-for="item in cat.items" :key="item.key" class="prep-item">
          <div class="prep-item-head">
            <el-tag size="small" :type="statusTagType(item.status)">{{ item.statusLabel }}</el-tag>
            <span class="prep-item-title">{{ item.title }}</span>
            <el-tag v-if="item.required" size="small" type="danger" effect="plain">必做</el-tag>
            <span v-else class="prep-optional">可选</span>
            <span class="prep-route">{{ item.route }}</span>
          </div>

          <div class="prep-item-desc">{{ item.description }}</div>

          <div v-if="item.stats.length" class="prep-stats">
            <span v-for="(s, i) in item.stats" :key="i" class="prep-stat">
              <span class="prep-stat-label">{{ s.label }}</span>
              <span class="prep-stat-value">{{ s.value }}</span>
            </span>
          </div>

          <ul v-if="item.warnings.length" class="prep-warnings">
            <li v-for="(w, i) in item.warnings" :key="i">{{ w }}</li>
          </ul>
          <div v-for="(n, i) in item.notes" :key="'n' + i" class="prep-note">{{ n }}</div>

          <el-collapse v-if="item.steps.length || item.details || item.extraTables.length" class="prep-sub">
            <el-collapse-item :name="item.key">
              <template #title>
                <span class="prep-sub-title">
                  操作步骤与数据明细
                  <template v-if="tablesOf(item).length">
                    （{{ tablesOf(item).length }} 张表）
                  </template>
                </span>
              </template>

              <ol v-if="item.steps.length" class="prep-steps">
                <li v-for="(step, i) in item.steps" :key="i">{{ step }}</li>
              </ol>

              <div v-for="(table, ti) in tablesOf(item)" :key="ti" class="prep-table-wrap">
                <div class="prep-table-title">{{ table.title || "明细" }}</div>
                <el-table :data="tableRows(table)" size="small" border stripe max-height="320">
                  <el-table-column
                    v-for="(col, ci) in table.columns"
                    :key="ci"
                    :label="col"
                    min-width="120"
                    show-overflow-tooltip
                  >
                    <template #default="{ row }">{{ row[ci] }}</template>
                  </el-table-column>
                </el-table>
                <div v-if="isTruncated(table)" class="prep-truncated">
                  仅显示前 {{ table.rows.length }} 条，共 {{ table.total }} 条；完整数据请导出 JSON。
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-collapse-item>
    </el-collapse>

    <el-empty v-else-if="!loading" description="未能获取准备清单" />

    <!-- 导入归档（分组） -->
    <PreparationImportDialog
      v-model="importVisible"
      :competition-id="props.competitionId ?? null"
      :competition-name="plan?.competition?.name || ''"
      :scope-options="scopeOptions"
      :initial-scope="importScope"
      @imported="onImported"
    />

    <template #footer>
      <span class="prep-footer-hint">
        导出文件为只读快照，可直接用于复用比赛设置与赛后归档；导入默认先预览、确认后才写库。
      </span>
      <el-button @click="visible = false">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { preparationApi, getErrorMessage } from "@/api";
import type {
  CompetitionPreparationPlan,
  PrepItemPlan,
  PrepStatus,
  PrepTable,
  PrepExportFormat,
  PrepScope,
  PrepScopeOption,
} from "@/types/api";
import PreparationImportDialog from "./PreparationImportDialog.vue";

const props = defineProps<{
  modelValue: boolean;
  /** 比赛 id；不传时后端取当前登录账号所属比赛 */
  competitionId?: number | null;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit("update:modelValue", v),
});

const loading = ref(false);
const exporting = ref<string | null>(null);
const plan = ref<CompetitionPreparationPlan | null>(null);
const activeGroups = ref<string[]>([]);

// ===== 分组导出 / 导入 =====
const scope = ref<PrepScope>("all");
const scopeOptions = ref<PrepScopeOption[]>([
  { value: "all", label: "全部准备数据", description: "导出/导入全部准备数据" },
]);
const importVisible = ref(false);
const importScope = ref<PrepScope>("all");

async function loadScopeOptions() {
  try {
    const res = (await preparationApi.scopes()) as { scopes?: PrepScopeOption[] };
    const list = res?.scopes || [];
    if (list.length) scopeOptions.value = list;
  } catch (e) {
    // 分组列表拿不到时保留「全部」兜底，不阻塞主流程
    console.error(e);
  }
}

function openImport(target: PrepScope) {
  importScope.value = target;
  importVisible.value = true;
}

function onImported() {
  load();
}

const summary = computed(
  () =>
    plan.value?.summary || {
      total: 0,
      required: 0,
      ready: 0,
      warning: 0,
      empty: 0,
      requiredWarning: 0,
      requiredEmpty: 0,
      warningCount: 0,
    },
);

function statusTagType(status: PrepStatus): "success" | "warning" | "info" {
  if (status === "ready") return "success";
  if (status === "warning") return "warning";
  return "info";
}

/** 明细表 → el-table 行对象（列顺序即表头顺序）。 */
function tableRows(table: PrepTable): Record<number, unknown>[] {
  return (table.rows || []).map((row) => ({ ...row }));
}

function tablesOf(item: PrepItemPlan): PrepTable[] {
  const out: PrepTable[] = [];
  if (item.details && item.details.rows?.length) out.push(item.details);
  for (const t of item.extraTables || []) if (t.rows?.length) out.push(t);
  return out;
}

function isTruncated(table: PrepTable): boolean {
  return typeof table.total === "number" && table.total > (table.rows?.length || 0);
}

async function load() {
  loading.value = true;
  try {
    plan.value = (await preparationApi.plan(props.competitionId ?? null)) as CompetitionPreparationPlan;
    // 默认展开所有含提醒或待准备事项的分组，便于直接看到待处理项
    activeGroups.value = (plan.value.categories || [])
      .filter((c) => c.summary.warning > 0 || c.summary.empty > 0)
      .map((c) => c.key);
  } catch (e) {
    ElMessage.error(getErrorMessage(e));
  } finally {
    loading.value = false;
  }
}

function onOpen() {
  plan.value = null;
  activeGroups.value = [];
  load();
  if (scopeOptions.value.length <= 1) loadScopeOptions();
}

/** 文件名安全字符过滤（与后端同口径：保留中日韩、字母数字、连字符与下划线）。 */
function safeName(raw: string): string {
  return (raw || "").replace(/[^\w\u4e00-\u9fff-]+/g, "_").replace(/^_+|_+$/g, "");
}

/** 本地时间戳 YYYYMMDD-HHmmss，与后端文件名格式保持一致。 */
function stamp(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}` +
    `-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
  );
}

/**
 * 构造下载文件名。
 * 说明：统一 axios 实例的响应拦截器只返回 res.data（Blob），拿不到响应头里的
 * Content-Disposition，故文件名在前端按同一命名规则本地生成。
 */
function buildFilename(format: PrepExportFormat, scopeKey?: PrepScope): string {
  const compName = safeName(plan.value?.competition?.name || "") || "competition";
  const compId = plan.value?.competition?.id ?? "";
  const ext = format === "markdown" ? "md" : "json";
  const scopePart =
    format === "json" && scopeKey
      ? `_${safeName(scopeOptions.value.find((o) => o.value === scopeKey)?.label || scopeKey)}`
      : "";
  return `比赛准备_${compName}_比赛${compId}${scopePart}_${stamp()}.${ext}`;
}

/** blob 型错误响应：读取响应体拿后端的具体错误信息（网络异常时静默回退）。 */
async function blobErrorMessage(e: unknown): Promise<string | null> {
  const data = (e as { response?: { data?: unknown } })?.response?.data;
  if (!(data instanceof Blob)) return null;
  try {
    const text = await data.text();
    const parsed = JSON.parse(text) as { message?: string };
    return parsed?.message || null;
  } catch {
    return null;
  }
}

/** 触发浏览器下载（blob → 临时 a 标签）。 */
function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // 释放对象 URL：延迟一拍，确保下载已开始
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** 导出：markdown 报告 或 全部 JSON 快照 */
async function handleExport(format: PrepExportFormat) {
  if (!plan.value) return;
  exporting.value = format;
  try {
    const res: any = await preparationApi.exportFile(format, props.competitionId ?? null);
    const blob: Blob = res instanceof Blob ? res : new Blob([res], { type: "text/plain;charset=utf-8" });
    const filename = buildFilename(format);
    triggerDownload(blob, filename);
    ElMessage.success(`已导出：${filename}`);
  } catch (e) {
    // 拦截器已弹过一次通用提示；blob 请求的业务错误信息需自行解码后补充，便于排查
    const specific = await blobErrorMessage(e);
    ElMessage.error(specific ? `导出失败：${specific}` : `导出失败：${getErrorMessage(e)}`);
  } finally {
    exporting.value = null;
  }
}

/** 按分组导出可再导入的 JSON 归档（分组按钮 / 顶部下拉 + 「导出本组」） */
async function handleExportArchive(scopeKey: PrepScope) {
  if (!plan.value) return;
  exporting.value = scopeKey;
  try {
    const res: any = await preparationApi.exportArchive(scopeKey, props.competitionId ?? null);
    const blob: Blob = res instanceof Blob ? res : new Blob([res], { type: "application/json;charset=utf-8" });
    const filename = buildFilename("json", scopeKey);
    triggerDownload(blob, filename);
    ElMessage.success(`已导出：${filename}`);
  } catch (e) {
    const specific = await blobErrorMessage(e);
    ElMessage.error(specific ? `导出失败：${specific}` : `导出失败：${getErrorMessage(e)}`);
  } finally {
    exporting.value = null;
  }
}

onMounted(loadScopeOptions);
</script>

<style scoped>
.prep-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.prep-comp {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
}
.prep-comp-label {
  color: #909399;
  font-size: 13px;
}
.prep-comp-name {
  font-weight: 600;
  color: #1f1f1f;
}
.prep-meta {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.prep-head-right {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.prep-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.prep-sum-card {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 10px 8px;
  text-align: center;
  background: #fafafa;
}
.prep-sum-num {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  line-height: 1.2;
}
.prep-sum-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.prep-sum-ready .prep-sum-num {
  color: #67c23a;
}
.prep-sum-warn .prep-sum-num {
  color: #e6a23c;
}
.prep-sum-empty .prep-sum-num {
  color: #909399;
}
.prep-alert {
  margin-bottom: 12px;
}
.prep-collapse {
  max-height: 58vh;
  overflow: auto;
  padding-right: 4px;
}
.prep-cat-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.prep-cat-name {
  font-weight: 600;
  font-size: 14px;
  color: #1f1f1f;
}
.prep-cat-desc {
  font-size: 12px;
  color: #909399;
  margin-bottom: 10px;
  line-height: 1.6;
}
.prep-cat-actions {
  margin-left: auto;
  margin-right: 8px;
  display: inline-flex;
  align-items: center;
}
.prep-scope-select {
  width: 150px;
}
.prep-item {
  border-left: 3px solid #dcdfe6;
  padding: 8px 0 8px 12px;
  margin-bottom: 10px;
}
.prep-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.prep-item-title {
  font-weight: 600;
  font-size: 14px;
  color: #303133;
}
.prep-optional {
  font-size: 12px;
  color: #c0c4cc;
}
.prep-route {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
  font-family: monospace;
}
.prep-item-desc {
  font-size: 13px;
  color: #606266;
  margin-top: 6px;
  line-height: 1.6;
}
.prep-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}
.prep-stat {
  font-size: 12px;
  background: #f4f4f5;
  border-radius: 4px;
  padding: 2px 8px;
}
.prep-stat-label {
  color: #909399;
}
.prep-stat-value {
  color: #303133;
  font-weight: 600;
  margin-left: 4px;
}
.prep-warnings {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #e6a23c;
  font-size: 12px;
  line-height: 1.7;
}
.prep-note {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}
.prep-sub {
  margin-top: 6px;
}
.prep-sub-title {
  font-size: 12px;
  color: #409eff;
}
.prep-steps {
  margin: 0 0 10px;
  padding-left: 20px;
  font-size: 13px;
  color: #606266;
  line-height: 1.8;
}
.prep-table-wrap {
  margin-bottom: 12px;
}
.prep-table-title {
  font-size: 12px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}
.prep-truncated {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.prep-footer-hint {
  float: left;
  font-size: 12px;
  color: #909399;
  line-height: 32px;
}
@media (max-width: 900px) {
  .prep-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .prep-collapse {
    max-height: 52vh;
  }
  .prep-route {
    margin-left: 0;
  }
}
</style>
