<template>
  <div class="dash">
    <div class="dash-bar">
      <span class="dash-title">仪表盘</span>
      <span v-if="!compStore.competitionId" class="dash-hint">
        （未选择比赛：仅可使用静态文字 / 手动数值控件；字段绑定需在比赛下进行）
      </span>
      <div class="dash-bar-right">
        <el-button size="small" :loading="loading" @click="refreshFields">刷新数据</el-button>
        <el-button v-if="widgets.length" size="small" type="danger" plain @click="clearAll">
          清空
        </el-button>
      </div>
    </div>

    <div class="dash-canvas" :class="{ 'is-empty': widgets.length === 0 }" @click.self="deselect">
      <!-- 字段数据（网络聚合）未确认前：画布保持空白 / 加载态，不渲染控件，
           避免控件先显示「—」再跳成真实值的跳变（首屏等网络再渲染）。 -->
      <div v-if="loading" class="dash-loading">
        <span class="dash-loading-text">正在加载数据…</span>
      </div>
      <template v-else>
      <div v-if="widgets.length === 0" class="dash-empty">
        <p class="dash-empty-title">空白仪表盘</p>
        <p class="dash-empty-sub">点击右下角 ＋ 添加控件（文字 / 仪表），控件可吸附网格自由拖动与缩放</p>
      </div>

      <DashboardWidget
        v-for="w in widgets"
        :key="w.id"
        :widget="w"
        :selected="w.id === selectedId"
        :bound-value="valueOf(w.config.fieldRef)"
        :bound-total-value="valueOf(w.config.totalField)"
        @patch="patchWidget(w, $event)"
        @edit="openEdit(w)"
        @remove="removeWidget(w)"
        @select="selectWidget(w)"
        @contextmenu="(p) => onWidgetCtx(w, p)"
      />

      <!-- 右下角圆形添加按钮 -->
      <div class="dash-fab-wrap">
        <div v-if="showAddMenu" class="dash-add-menu">
          <button class="dash-add-item" @click="addWidget('text')">＋ 文字控件</button>
          <button class="dash-add-item" @click="addWidget('gauge')">＋ 仪表控件</button>
          <button class="dash-add-item" @click="addWidget('table')">＋ 表格控件</button>
          <template v-if="customWidgets.length">
            <div class="dash-add-sep"></div>
            <button
              v-for="cw in customWidgets"
              :key="cw.type"
              class="dash-add-item"
              :title="cw.description || ''"
              @click="addWidget(cw.type)"
            >
              ＋ {{ cw.label }}
            </button>
          </template>
        </div>
        <button class="dash-fab" title="添加控件" @click="toggleAddMenu">＋</button>
      </div>
      </template>
    </div>

    <!-- 右键上下文菜单 -->
    <div
      v-if="ctx"
      class="dw-ctx-mask"
      @click="ctx = null"
      @contextmenu.prevent="ctx = null"
    ></div>
    <div
      v-if="ctx"
      class="dw-ctx"
      :style="{ left: ctx.x + 'px', top: ctx.y + 'px' }"
      @click.stop
    >
      <button class="dw-ctx-item" @click="ctxEdit">✎ 编辑</button>
      <button class="dw-ctx-item danger" @click="ctxRemove">🗑 删除</button>
    </div>

    <!-- 编辑对话框 -->
    <el-dialog v-model="showEdit" :title="editTitle" width="460px" append-to-body>
      <el-form label-width="100px">
        <template v-if="editing?.type === 'text'">
          <el-form-item label="绑定字段">
            <el-select
              v-model="editForm.fieldKey"
              placeholder="可选：绑定一个可查看字段"
              clearable
              filterable
              style="width: 100%"
            >
              <el-option v-for="f in fields" :key="f.key" :label="f.label" :value="f.key" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editForm.fieldKey" label="标题/说明">
            <el-input v-model="editForm.caption" placeholder="显示在内容上方（默认取字段名）" />
          </el-form-item>
          <el-form-item v-else label="文字内容">
            <el-input
              v-model="editForm.text"
              type="textarea"
              :rows="3"
              placeholder="直接展示的文字内容"
            />
          </el-form-item>
        </template>

        <template v-else-if="editing?.type === 'table'">
          <el-form-item label="绑定字段">
            <el-select
              v-model="editForm.fieldKey"
              placeholder="可选：直接显示该字段的字典值"
              clearable
              filterable
              style="width: 100%"
            >
              <el-option v-for="f in fields" :key="f.key" :label="f.label" :value="f.key" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="!editForm.fieldKey" label="字典内容">
            <el-input
              v-model="editForm.dictText"
              type="textarea"
              :rows="6"
              placeholder="填写 JSON 对象，如 {项目A:10, 项目B:20}"
            />
          </el-form-item>
          <el-form-item v-else label="提示">
            <span class="dw-tip">将显示该字段当前的字典值（键 / 值两列）</span>
          </el-form-item>
          <el-form-item label="标题">
            <el-input v-model="editForm.caption" placeholder="可选，显示在表格上方" />
          </el-form-item>
        </template>

        <!-- 自定义控件：可绑定字段（若 bindable）+ 自定义配置 JSON -->
        <template v-else-if="editingCustomDef">
          <el-form-item v-if="editingCustomDef?.bindable" label="绑定字段">
            <el-select
              v-model="editForm.fieldKey"
              placeholder="可选：绑定一个可查看字段，组件经 props.value 读取"
              clearable
              filterable
              style="width: 100%"
            >
              <el-option v-for="f in fields" :key="f.key" :label="f.label" :value="f.key" />
            </el-select>
          </el-form-item>
          <el-form-item label="自定义配置 (JSON)">
            <el-input
              v-model="editForm.customText"
              type="textarea"
              :rows="10"
              placeholder='{"key": "value"}'
            />
          </el-form-item>
          <el-form-item v-if="editingCustomDef?.description" label="说明">
            <span class="dw-tip">{{ editingCustomDef.description }}</span>
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="标题">
            <el-input v-model="editForm.label" placeholder="如：预算使用率" />
          </el-form-item>
          <el-form-item label="总量绑定">
            <el-select
              v-model="editForm.totalFieldKey"
              placeholder="可选：总量取自字段当前值"
              clearable
              filterable
              style="width: 100%"
            >
              <el-option v-for="f in fields" :key="f.key" :label="f.label" :value="f.key" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="!editForm.totalFieldKey" label="总量">
            <el-input-number
              v-model="editForm.total"
              :min="0"
              :step="1"
              controls-position="right"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item v-else label="提示">
            <span class="dw-tip">总量将自动取自绑定字段的当前值</span>
          </el-form-item>
          <el-form-item label="展示量绑定">
            <el-select
              v-model="editForm.fieldKey"
              placeholder="可选：展示量取自字段当前值"
              clearable
              filterable
              style="width: 100%"
            >
              <el-option v-for="f in fields" :key="f.key" :label="f.label" :value="f.key" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="!editForm.fieldKey" label="展示量">
            <el-input-number
              v-model="editForm.display"
              :min="0"
              :step="1"
              controls-position="right"
              style="width: 100%"
            />
          </el-form-item>
          <el-form-item v-else label="提示">
            <span class="dw-tip">展示量将自动取自绑定字段的当前值</span>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import DashboardWidget from "@/components/dashboard/DashboardWidget.vue";
import {
  createWidget,
  listCustomWidgets,
  isCustomType,
  isBuiltinType,
  getCustomWidget,
  type WidgetConfig,
} from "@/components/dashboard/types";
import {
  useDashboardFields,
  type SelectableField,
} from "@/composables/useDashboardFields";
import { useCompetitionStore } from "@/stores/competition";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const { fields, loading, load, valueOf, refKey } = useDashboardFields();

const widgets = ref<WidgetConfig[]>([]);
const selectedId = ref<string | null>(null);
const showAddMenu = ref(false);
const ctx = ref<{ x: number; y: number; widget: WidgetConfig } | null>(null);

/** 已注册自定义控件列表，用于「添加控件」菜单动态展开 */
const customWidgets = computed(() => listCustomWidgets());

function onWidgetCtx(w: WidgetConfig, p: { x: number; y: number }) {
  selectWidget(w);
  ctx.value = { x: p.x, y: p.y, widget: w };
}
function ctxEdit() {
  if (ctx.value) openEdit(ctx.value.widget);
  ctx.value = null;
}
function ctxRemove() {
  if (ctx.value) removeWidget(ctx.value.widget);
  ctx.value = null;
}

const storageKey = computed(() => {
  // 按账号 + 比赛隔离：不同账号（即使同一浏览器/同一比赛）互不共享仪表盘布局。
  const uid = authStore.user?.id ?? "guest";
  return `dashboard.widgets.v1.u${uid}.c${compStore.competitionId ?? "none"}`;
});

function loadWidgets() {
  try {
    const raw = localStorage.getItem(storageKey.value);
    const arr = raw ? (JSON.parse(raw) as any[]) : [];
    // 兼容旧版：仅有单一 size 的控件迁移为独立的宽 w / 高 h
    const migrated = arr.map((w) => {
      if (w && typeof w.size === "number" && typeof w.w !== "number") {
        return { ...w, w: w.size, h: w.size, size: undefined };
      }
      return w as WidgetConfig;
    });
    // 丢弃类型未注册（既非内置、也非已注册自定义）的控件，
    // 例如已被移除的「计数卡」(example-counter)，避免它被渲染成「未知控件」占位。
    widgets.value = migrated.filter(
      (w) => isBuiltinType(w.type) || isCustomType(w.type),
    );
  } catch {
    widgets.value = [];
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;
function saveWidgets() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(storageKey.value, JSON.stringify(widgets.value));
    } catch {
      /* 忽略写入失败 */
    }
  }, 200);
}

watch(widgets, saveWidgets, { deep: true });
watch(storageKey, () => loadWidgets());

function selectWidget(w: WidgetConfig) {
  selectedId.value = w.id;
}
function deselect() {
  selectedId.value = null;
  showAddMenu.value = false;
  ctx.value = null;
}
function patchWidget(w: WidgetConfig, p: Partial<WidgetConfig>) {
  Object.assign(w, p);
}
function toggleAddMenu() {
  showAddMenu.value = !showAddMenu.value;
}
function addWidget(type: string) {
  const w = createWidget(type, widgets.value.length);
  widgets.value.push(w);
  selectedId.value = w.id;
  showAddMenu.value = false;
  openEdit(w);
}
function removeWidget(w: WidgetConfig) {
  widgets.value = widgets.value.filter((x) => x.id !== w.id);
  if (selectedId.value === w.id) selectedId.value = null;
}
function clearAll() {
  ElMessageBox.confirm("清空仪表盘上所有控件？此操作不可撤销。", { type: "warning" })
    .then(() => {
      widgets.value = [];
      selectedId.value = null;
    })
    .catch(() => {});
}

// ===== 编辑对话框 =====
const showEdit = ref(false);
const editing = ref<WidgetConfig | null>(null);
const editForm = ref({
  fieldKey: "",
  totalFieldKey: "",
  caption: "",
  text: "",
  label: "",
  total: 0,
  display: 0,
  dictText: "",
  customText: "",
});

function fieldByKey(key: string): SelectableField | undefined {
  return fields.value.find((f) => f.key === key);
}

function openEdit(w: WidgetConfig) {
  editing.value = w;
  const c = w.config;
  editForm.value = {
    fieldKey: c.fieldRef ? refKey(c.fieldRef) : "",
    totalFieldKey: c.totalField ? refKey(c.totalField) : "",
    caption: c.caption || "",
    text: c.text || "",
    label: c.label || "",
    total: c.total ?? 0,
    display: c.display ?? 0,
    dictText: c.dict ? JSON.stringify(c.dict, null, 2) : "",
    customText: c.custom ? JSON.stringify(c.custom, null, 2) : "{}",
  };
  showEdit.value = true;
}

const editTitle = computed(() => {
  const w = editing.value;
  if (!w) return "编辑控件";
  const t = w.type;
  if (t === "gauge") return "编辑仪表控件";
  if (t === "table") return "编辑表格控件";
  if (t === "text") return "编辑文字控件";
  const cdef = getCustomWidget(t);
  return cdef ? `编辑${cdef.label}` : "编辑控件";
});

/** 当前正在编辑的控件若是已注册自定义控件，返回其定义 */
const editingCustomDef = computed(() =>
  editing.value ? getCustomWidget(editing.value.type) : undefined,
);

function saveEdit() {
  const w = editing.value;
  if (!w) return;
  const ref = editForm.value.fieldKey
    ? fieldByKey(editForm.value.fieldKey)?.ref
    : undefined;
  if (w.type === "text") {
    w.config = ref
      ? { fieldRef: ref, caption: editForm.value.caption }
      : { fieldRef: undefined, text: editForm.value.text };
  } else if (w.type === "table") {
    let dict: Record<string, unknown> | undefined;
    if (!ref) {
      const raw = editForm.value.dictText?.trim();
      if (raw) {
        try {
          dict = JSON.parse(raw);
        } catch {
          dict = undefined;
        }
      } else {
        dict = {};
      }
    }
    w.config = ref
      ? { fieldRef: ref, caption: editForm.value.caption }
      : { fieldRef: undefined, dict, caption: editForm.value.caption };
  } else if (isCustomType(w.type)) {
    // 自定义控件：解析 JSON 配置并写入 config.custom；bindable 时写入绑定字段
    let custom: Record<string, unknown> = {};
    const raw = editForm.value.customText?.trim();
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          custom = parsed as Record<string, unknown>;
        } else {
          ElMessage.error("自定义配置必须是 JSON 对象");
          return;
        }
      } catch {
        ElMessage.error("自定义配置不是合法 JSON");
        return;
      }
    }
    const cdef = getCustomWidget(w.type);
    const fieldRef = cdef?.bindable ? ref : undefined;
    w.config = { custom, fieldRef };
  } else {
    const totalRef = editForm.value.totalFieldKey
      ? fieldByKey(editForm.value.totalFieldKey)?.ref
      : undefined;
    w.config = {
      fieldRef: ref,
      totalField: totalRef,
      label: editForm.value.label,
      total: Number(editForm.value.total) || 0,
      display: Number(editForm.value.display) || 0,
    };
  }
  showEdit.value = false;
  ElMessage.success("已保存");
}

function refreshFields() {
  load();
}

// 实时数据变更 → 重新拉取字段值（公司字段 / 区域总览 / 地图节点区域变更 / 消费者需求）
useResourceChanged("company-field", () => load());
useResourceChanged("region", () => load());
useResourceChanged("map-nodes", () => load());
useResourceChanged("consumer-demand", () => load());

onMounted(() => {
  loadWidgets();
});
onBeforeUnmount(() => {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
});
</script>

<style scoped>
.dash {
  display: flex;
  flex-direction: column;
  /* 用 flex:1 撑满父级（route-wrap 已为 flex 列容器），替代原 height:100%。
     height:100% 在父级无确定高度时会解析失败导致画布塌缩、背景圆点铺不满下方。
     min-height:0 允许内部 .dash-canvas 正确收缩/滚动。 */
  flex: 1;
  min-height: 0;
}
.dash-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 4px 12px;
}
.dash-title {
  position: relative;
  font-size: var(--font-2xl);
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
  padding-left: 14px;
}
.dash-title::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 18px;
  border-radius: 4px;
  background: var(--gradient-brand);
}
.dash-hint {
  font-size: 12px;
  color: #909399;
}
.dash-bar-right {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.dash-canvas {
  position: relative;
  flex: 1;
  overflow: auto;
  min-height: 600px;
  border-radius: 10px;
  background-color: #f7f8fa;
  background-image: radial-gradient(circle, #d4d7dd 1.4px, transparent 1.4px);
  background-size: 20px 20px;
}
.dash-empty {
  position: absolute;
  top: 40%;
  left: 0;
  right: 0;
  text-align: center;
  color: #b4b9c2;
  pointer-events: none;
}
.dash-loading {
  position: absolute;
  top: 40%;
  left: 0;
  right: 0;
  text-align: center;
  color: #909399;
  pointer-events: none;
}
.dash-loading::before {
  content: "";
  display: block;
  width: 30px;
  height: 30px;
  margin: 0 auto 12px;
  border: 3px solid #e3e6eb;
  border-top-color: #409eff;
  border-radius: 50%;
  animation: dash-spin 0.8s linear infinite;
}
@keyframes dash-spin {
  to {
    transform: rotate(360deg);
  }
}
.dash-loading-text {
  font-size: 13px;
}
.dash-empty-title {
  font-size: 18px;
  margin: 0 0 8px;
}
.dash-empty-sub {
  font-size: 13px;
  margin: 0;
}

.dash-fab-wrap {
  position: absolute;
  right: 28px;
  bottom: 28px;
  z-index: 20;
}
.dash-fab {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  border: none;
  font-size: 30px;
  line-height: 1;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(64, 158, 255, 0.4);
  transition: transform 0.15s;
}
.dash-fab:hover {
  transform: scale(1.06);
}
.dash-add-menu {
  position: absolute;
  right: 0;
  bottom: 66px;
  background: #fff;
  border: 1px solid #e3e6eb;
  border-radius: 10px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.dash-add-item {
  border: none;
  background: none;
  padding: 11px 20px;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
  color: #303133;
  font-size: 14px;
}
.dash-add-item:hover {
  background: #f0f6ff;
}
.dash-add-sep {
  height: 1px;
  background: #eef0f3;
  margin: 2px 8px;
}
.dw-tip {
  font-size: 12px;
  color: #909399;
}

.dw-ctx-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
}
.dw-ctx {
  position: fixed;
  z-index: 101;
  min-width: 116px;
  background: #fff;
  border: 1px solid #e3e6eb;
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.16);
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.dw-ctx-item {
  border: none;
  background: none;
  text-align: left;
  padding: 8px 12px;
  border-radius: 7px;
  cursor: pointer;
  color: #303133;
  font-size: 14px;
  line-height: 1.2;
  white-space: nowrap;
}
.dw-ctx-item:hover {
  background: #f0f6ff;
}
.dw-ctx-item.danger {
  color: #f56c6c;
}
.dw-ctx-item.danger:hover {
  background: #fef0f0;
}
</style>
