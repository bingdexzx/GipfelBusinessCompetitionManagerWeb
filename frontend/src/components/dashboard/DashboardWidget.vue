<template>
  <div
    class="dw-widget"
    :class="{ selected }"
    :style="{
      left: widget.x + 'px',
      top: widget.y + 'px',
      width: widget.w + 'px',
      height: widget.h + 'px',
    }"
    @pointerdown="onDown"
    @contextmenu.prevent="onCtx"
  >
    <!-- 文字控件 -->
    <div v-if="widget.type === 'text'" class="dw-text-wrap">
      <div v-if="isField && textCaption" class="dw-cap">{{ textCaption }}</div>
      <div class="dw-text" :class="{ 'dw-text-empty': !textContent }" :style="textStyle">{{ textContent || "点击编辑填写文字" }}</div>
    </div>

    <!-- 表格控件：字典 → 键/值两列，可滚动 -->
    <div v-else-if="widget.type === 'table'" class="dw-table-wrap">
      <div v-if="textCaption" class="dw-cap">{{ textCaption }}</div>
      <div class="dw-table-scroll">
        <table v-if="tableEntries.length" class="dw-table">
          <tbody>
            <tr v-for="([k, v], i) in tableEntries" :key="i">
              <td class="dw-td-key">{{ k }}</td>
              <td class="dw-td-val">{{ fmt(v) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-else class="dw-table-empty">（无数据）</div>
      </div>
    </div>

    <!-- 自定义控件：已注册则渲染其组件，并传入 widget / value / totalValue -->
    <component
      v-else-if="customDef"
      :is="customDef.component"
      :widget="widget"
      :value="boundValue"
      :total-value="boundTotalValue"
    />

    <!-- 仪表控件 -->
    <svg v-else-if="widget.type === 'gauge'" class="dw-gauge" viewBox="0 0 120 120" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient :id="gradId" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stop-color="#36cfc9" />
          <stop offset="100%" stop-color="#4096ff" />
        </linearGradient>
      </defs>
      <path :d="trackPath" fill="none" stroke="#eef0f3" stroke-width="12" stroke-linecap="round" />
      <path
        v-if="fillPath"
        :d="fillPath"
        fill="none"
        :stroke="`url(#${gradId})`"
        stroke-width="12"
        stroke-linecap="round"
      />
      <text v-if="widget.config.label" x="60" y="48" text-anchor="middle" class="dw-g-label">
        {{ widget.config.label }}
      </text>
      <text x="60" y="74" text-anchor="middle" class="dw-g-pct">{{ pctText }}</text>
      <text x="60" y="92" text-anchor="middle" class="dw-g-rem">剩余 {{ remainText }}</text>
    </svg>

    <!-- 未知控件占位（类型未注册为自定义，又非内置） -->
    <div v-else class="dw-unknown">
      <span>未知控件</span>
      <small>{{ widget.type }}</small>
    </div>

    <!-- 选中时的工具条与缩放柄 -->
    <div v-if="selected" class="dw-tool">
      <button title="编辑" @pointerdown.stop @click.stop="emit('edit')">✎</button>
      <button title="删除" @pointerdown.stop @click.stop="emit('remove')">✕</button>
    </div>
    <div
      v-if="selected"
      class="dw-resize"
      title="拖动缩放"
      @pointerdown="onResizeDown"
    ></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { WidgetConfig } from "./types";
import { getCustomWidget } from "./types";

const props = defineProps<{
  widget: WidgetConfig;
  selected: boolean;
  boundValue: unknown;
  boundTotalValue: unknown;
}>();

const emit = defineEmits<{
  (e: "patch", p: Partial<WidgetConfig>): void;
  (e: "edit"): void;
  (e: "remove"): void;
  (e: "select"): void;
  (e: "contextmenu", payload: { x: number; y: number }): void;
}>();

const GRID = 20;
const MIN = 100; // 20 的整数倍，避免吸附时突变
const MAX = 480;
const clamp = (v: number) => Math.max(MIN, Math.min(MAX, v));
const snap = (v: number) => Math.round(v / GRID) * GRID;

// ===== 拖拽 / 缩放（指针事件）=====
let dragging = false;
let sx = 0;
let sy = 0;
let ox = 0;
let oy = 0;
let resizing = false;
let rsx = 0;
let rsy = 0;
let ow = 0;
let oh = 0;

function onMove(e: PointerEvent) {
  if (dragging) {
    emit("patch", { x: ox + (e.clientX - sx), y: oy + (e.clientY - sy) });
  } else if (resizing) {
    // 非等比缩放：宽度随横向拖动、高度随纵向拖动，各自独立
    emit("patch", {
      w: clamp(ow + (e.clientX - rsx)),
      h: clamp(oh + (e.clientY - rsy)),
    });
  }
}
function onUp() {
  if (dragging) {
    dragging = false;
    emit("patch", { x: snap(props.widget.x), y: snap(props.widget.y) });
  }
  if (resizing) {
    resizing = false;
    // 缩放过程中自由跟随，松手后宽高各自吸附到最近的网格线
    emit("patch", {
      w: clamp(snap(props.widget.w)),
      h: clamp(snap(props.widget.h)),
    });
  }
  window.removeEventListener("pointermove", onMove);
  window.removeEventListener("pointerup", onUp);
}
function onDown(e: PointerEvent) {
  const t = e.target as HTMLElement;
  if (t.closest(".dw-tool") || t.closest(".dw-resize")) return;
  if (e.button !== 0) return; // 仅左键拖拽；右键交由 contextmenu 处理
  emit("select");
  dragging = true;
  sx = e.clientX;
  sy = e.clientY;
  ox = props.widget.x;
  oy = props.widget.y;
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  e.preventDefault();
}
function onCtx(e: MouseEvent) {
  emit("select");
  emit("contextmenu", { x: e.clientX, y: e.clientY });
}
function onResizeDown(e: PointerEvent) {
  emit("select");
  resizing = true;
  rsx = e.clientX;
  rsy = e.clientY;
  ow = props.widget.w;
  oh = props.widget.h;
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
  e.preventDefault();
  e.stopPropagation();
}

// ===== 内容 =====
function fmt(v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "object") {
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }
  return String(v);
}

const isField = computed(() => !!props.widget.config.fieldRef);
/** 若当前控件是已注册的自定义控件，返回其定义；否则 undefined */
const customDef = computed(() => getCustomWidget(props.widget.type));
const textContent = computed(() => {
  if (props.widget.type !== "text") return "";
  return isField.value ? fmt(props.boundValue) : props.widget.config.text || "";
});
const textCaption = computed(() => props.widget.config.caption || "");
const textStyle = computed(() => ({
  fontSize:
    Math.max(11, Math.round(Math.min(props.widget.w, props.widget.h) * 0.13)) +
    "px",
}));

// 表格控件：取字典（绑定字段优先，否则静态 dict），转键值对数组
const tableEntries = computed<[string, unknown][]>(() => {
  if (props.widget.type !== "table") return [];
  let src: unknown = props.widget.config.fieldRef
    ? props.boundValue
    : props.widget.config.dict;
  // 产业字段（公司字段）的字典值以 JSON 字符串形式存储，需解析
  if (typeof src === "string") {
    const t = src.trim();
    if (t) {
      try {
        src = JSON.parse(t);
      } catch {
        /* 非 JSON 字符串：保持原样（交由下方兜底为空） */
      }
    }
  }
  if (!src || typeof src !== "object") return [];
  if (Array.isArray(src)) {
    // 支持数组形式：元素为 [key, value]、{key,value} / {k,v} / {name,value}
    return src
      .map((it) => {
        if (Array.isArray(it) && it.length >= 2) return [String(it[0]), it[1]] as [string, unknown];
        if (it && typeof it === "object") {
          const o = it as Record<string, unknown>;
          const k = o.key ?? o.k ?? o.name ?? o.label;
          const v = o.value ?? o.v;
          if (k != null) return [String(k), v] as [string, unknown];
        }
        return null;
      })
      .filter((x): x is [string, unknown] => x !== null);
  }
  return Object.entries(src as Record<string, unknown>);
});

// ===== 仪表 =====
const gaugePct = computed(() => {
  if (props.widget.type !== "gauge") return -1;
  const c = props.widget.config;
  // 总量：优先取绑定字段值，否则用手填值
  const total = c.totalField
    ? Number(props.boundTotalValue)
    : Number(c.total) || 0;
  const totalValid = isFinite(total) && total > 0;
  const display = isField.value ? Number(props.boundValue) : Number(c.display) || 0;
  if (!isFinite(display) || !totalValid) return -1; // 无效
  const p = (display / total) * 100;
  return Math.max(0, Math.min(100, p));
});

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function arc(cx: number, cy: number, r: number, start: number, end: number): string {
  const [x0, y0] = polar(cx, cy, r, start);
  const [x1, y1] = polar(cx, cy, r, end);
  const large = end - start > 180 ? 1 : 0;
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}
const START = 135;
const SWEEP = 270;
const trackPath = computed(() => arc(60, 60, 48, START, START + SWEEP));
const fillPath = computed(() => {
  const p = gaugePct.value < 0 ? 0 : gaugePct.value;
  return p <= 0 ? "" : arc(60, 60, 48, START, START + (SWEEP * p) / 100);
});
const pctText = computed(() => (gaugePct.value < 0 ? "—" : `${Math.round(gaugePct.value)}%`));
const remainText = computed(() =>
  gaugePct.value < 0 ? "—" : `${Math.round(100 - gaugePct.value)}%`,
);
const gradId = computed(() => `gaugeGrad-${props.widget.id}`);
</script>

<style scoped>
.dw-widget {
  position: absolute;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
  border: 1px solid #e3e6eb;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  user-select: none;
  cursor: grab;
  overflow: hidden;
  box-sizing: border-box;
}
.dw-widget:active {
  cursor: grabbing;
}
.dw-widget.selected {
  outline: 2px solid #409eff;
  outline-offset: 2px;
}

.dw-text-wrap {
  padding: 10px 14px;
  width: 100%;
  box-sizing: border-box;
}
.dw-cap {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dw-text {
  font-weight: 600;
  color: #1f2d3d;
  line-height: 1.35;
  word-break: break-word;
  white-space: pre-wrap;
}
.dw-text-empty {
  font-weight: 400;
  color: #c0c4cc;
}

.dw-table-wrap {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  padding: 8px 10px;
  box-sizing: border-box;
}
.dw-table-scroll {
  flex: 1;
  overflow: auto;
  margin-top: 4px;
}
.dw-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.dw-table td {
  border: 1px solid #eef0f3;
  padding: 4px 8px;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}
.dw-td-key {
  color: #606266;
  background: #fafbfc;
  width: 42%;
  font-weight: 500;
}
.dw-td-val {
  color: #1f2d3d;
  font-weight: 600;
}
.dw-table-empty {
  color: #909399;
  font-size: 12px;
  padding: 8px;
  text-align: center;
}

.dw-gauge {
  width: 100%;
  height: 100%;
}
.dw-g-label {
  font-size: 11px;
  fill: #606266;
}
.dw-g-pct {
  font-size: 22px;
  font-weight: 700;
  fill: #1f2d3d;
}
.dw-g-rem {
  font-size: 9px;
  fill: #909399;
}

.dw-tool {
  position: absolute;
  top: -16px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 2px;
  background: #fff;
  border: 1px solid #e3e6eb;
  border-radius: 12px;
  padding: 2px 6px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
  z-index: 2;
}
.dw-tool button {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 14px;
  color: #606266;
  padding: 2px 4px;
  line-height: 1;
}
.dw-tool button:hover {
  color: #409eff;
}
.dw-resize {
  position: absolute;
  right: 6px;
  bottom: 6px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #409eff;
  cursor: nwse-resize;
  z-index: 2;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

.dw-unknown {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  width: 100%;
  height: 100%;
  color: #f56c6c;
  font-size: 13px;
}
.dw-unknown small {
  color: #c0c4cc;
  font-size: 11px;
  word-break: break-all;
  padding: 0 8px;
}
</style>
