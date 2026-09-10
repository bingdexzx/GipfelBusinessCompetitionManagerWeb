# 自定义仪表盘控件开发指南

## 概述

仪表盘支持自定义控件扩展。你只需要：
1. 写一个 Vue 组件
2. 在注册文件中注册
3. 重新构建前端

控件会自动出现在仪表盘的「添加控件」菜单中，支持拖拽、缩放、编辑配置。

---

## 快速开始（3 分钟上手）

### 第一步：创建控件组件

在 `frontend/src/components/dashboard/widgets/` 目录下新建你的组件文件：

```bash
frontend/src/components/dashboard/widgets/MyWidget.vue
```

最简单的控件模板：

```vue
<template>
  <div class="my-widget">
    <div class="my-title">{{ config.title || '我的控件' }}</div>
    <div class="my-value">{{ displayValue }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { CustomWidgetProps } from "../types";

// 必须声明这三个 props（名称和类型必须一致）
const props = defineProps<CustomWidgetProps>();

// 从 config.custom 读取自定义配置
const config = computed(() => (props.widget.config.custom || {}) as Record<string, unknown>);

// 如果用户绑定了字段，props.value 就是字段的当前值
const displayValue = computed(() => {
  if (props.value != null) return String(props.value);
  return config.value.defaultValue ?? "—";
});
</script>

<style scoped>
.my-widget {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 12px;
  box-sizing: border-box;
}
.my-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}
.my-value {
  font-size: 24px;
  font-weight: 700;
  color: #1f2d3d;
}
</style>
```

### 第二步：注册控件

编辑 `frontend/src/components/dashboard/registerCustomWidgets.ts`：

```typescript
import { registerCustomWidget } from "./types";
import MyWidget from "./widgets/MyWidget.vue";

registerCustomWidget({
  type: "my-widget",           // 唯一标识（英文，持久化到 localStorage）
  label: "我的控件",            // 「添加控件」菜单中显示的名称
  component: MyWidget,         // 你的 Vue 组件
  bindable: true,              // true = 编辑弹窗出现「绑定字段」下拉
  description: "一个示例控件",  // 编辑弹窗中的说明文字（可选）
  defaultSize: { w: 200, h: 150 },  // 默认尺寸（可选，默认 220×160）
  defaultConfig: {             // 默认自定义配置（可选）
    title: "示例标题",
    defaultValue: 0,
  },
});
```

### 第三步：构建

```bash
cd frontend
npm run build
```

完成！打开仪表盘，点击右下角 ＋ 号，你会看到「我的控件」选项。

---

## 控件 Props 契约

你的组件**必须**声明以下三个 props：

| Prop | 类型 | 说明 |
|------|------|------|
| `widget` | `WidgetConfig` | 控件的完整配置（位置、尺寸、config.custom 等） |
| `value` | `unknown` | 用户绑定的字段的当前值（未绑定时为 `undefined`） |
| `totalValue` | `unknown` | 用户绑定的「总量字段」的当前值（未绑定时为 `undefined`） |

在 `<script setup>` 中这样声明：

```typescript
import type { CustomWidgetProps } from "../types";
const props = defineProps<CustomWidgetProps>();
```

---

## 注册选项详解

```typescript
registerCustomWidget({
  // ===== 必填 =====
  type: "my-widget",        // string: 唯一标识，不能与内置类型(text/gauge/table)重名
  label: "我的控件",         // string: 菜单显示名
  component: MyWidget,       // Component: Vue 组件

  // ===== 可选 =====
  defaultSize: { w: 200, h: 150 },  // 默认宽高(px)
  bindable: true,           // 是否允许绑定字段（默认 false）
  description: "说明文字",    // 编辑弹窗中的说明
  defaultConfig: {},         // 默认 custom 配置对象
});
```

---

## 读取配置

用户在编辑弹窗中填写的 JSON 配置存储在 `widget.config.custom` 中：

```typescript
const config = computed(() => {
  return (props.widget.config.custom || {}) as Record<string, unknown>;
});

// 读取配置项
const title = computed(() => config.value.title ?? "默认标题");
const color = computed(() => config.value.color ?? "#409eff");
```

用户在编辑弹窗的「自定义配置 (JSON)」文本框中直接编辑 JSON：

```json
{
  "title": "预算使用率",
  "color": "#67c23a",
  "showIcon": true
}
```

---

## 读取绑定字段值

当 `bindable: true` 时，用户可以在编辑弹窗中选择一个字段绑定。字段的实时值通过 `props.value` 传入：

```typescript
import { computed } from "vue";

// props.value 可能是 string / number / object / undefined
const fieldValue = computed(() => props.value);

// 按类型处理
const numericValue = computed(() => {
  const v = props.value;
  if (v == null) return 0;
  const n = Number(v);
  return isFinite(n) ? n : 0;
});

// 字典类型的字段值（如表格数据）
const dictValue = computed(() => {
  if (typeof props.value === "string") {
    try { return JSON.parse(props.value); } catch { return null; }
  }
  return props.value;
});
```

---

## 完整示例：进度条控件

`frontend/src/components/dashboard/widgets/ProgressBar.vue`：

```vue
<template>
  <div class="pb-wrap">
    <div v-if="config.title" class="pb-title">{{ config.title }}</div>
    <div class="pb-bar-bg">
      <div class="pb-bar-fill" :style="{ width: pct + '%', background: color }"></div>
    </div>
    <div class="pb-label">{{ displayValue }} / {{ displayTotal }} ({{ pct }}%)</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { CustomWidgetProps } from "../types";

const props = defineProps<CustomWidgetProps>();

const config = computed(() => (props.widget.config.custom || {}) as Record<string, unknown>);
const color = computed(() => (config.value.color as string) || "#409eff");

const displayValue = computed(() => {
  const v = props.value;
  return v != null ? Number(v) : Number(config.value.current ?? 0);
});

const displayTotal = computed(() => {
  const v = props.totalValue;
  return v != null ? Number(v) : Number(config.value.total ?? 100);
});

const pct = computed(() => {
  const t = displayTotal.value;
  if (!t || t <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((displayValue.value / t) * 100)));
});
</script>

<style scoped>
.pb-wrap {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 14px 16px;
  box-sizing: border-box;
  gap: 8px;
}
.pb-title {
  font-size: 12px;
  color: #909399;
  font-weight: 500;
}
.pb-bar-bg {
  height: 12px;
  background: #ebeef5;
  border-radius: 6px;
  overflow: hidden;
}
.pb-bar-fill {
  height: 100%;
  border-radius: 6px;
  transition: width 0.3s ease;
}
.pb-label {
  font-size: 12px;
  color: #606266;
  text-align: right;
}
</style>
```

注册：

```typescript
// registerCustomWidgets.ts
import { registerCustomWidget } from "./types";
import ProgressBar from "./widgets/ProgressBar.vue";

registerCustomWidget({
  type: "progress-bar",
  label: "进度条",
  component: ProgressBar,
  bindable: true,
  description: "展示进度百分比，可绑定展示量和总量字段",
  defaultSize: { w: 240, h: 80 },
  defaultConfig: { title: "进度", color: "#409eff", current: 0, total: 100 },
});
```

---

## 不绑定字段、纯靠自定义配置的控件

如果你的控件不需要绑定仪表盘字段（比如自行调 API 取数据），设 `bindable: false`：

```typescript
registerCustomWidget({
  type: "clock",
  label: "时钟",
  component: ClockWidget,
  bindable: false,  // 不出现「绑定字段」下拉
});
```

此时 `props.value` 和 `props.totalValue` 始终为 `undefined`。

---

## WidgetConfig 完整结构参考

```typescript
interface WidgetConfig {
  id: string;          // 自动生成的唯一 ID
  type: string;        // 控件类型标识
  x: number;           // 左上角 X 坐标(px)
  y: number;           // 左上角 Y 坐标(px)
  w: number;           // 宽度(px)
  h: number;           // 高度(px)
  config: {
    fieldRef?: FieldRef;  // 绑定的字段引用
    caption?: string;     // 标题/说明
    text?: string;        // 文字内容
    label?: string;       // 仪表标签
    total?: number | string;  // 总量
    totalField?: FieldRef;    // 总量字段引用
    display?: number;     // 展示量
    dict?: Record<string, unknown>;  // 字典数据
    custom?: Record<string, unknown>;  // ← 你的自定义配置在这里
  };
}
```

你只需要关心 `widget.config.custom` 和 `props.value` / `props.totalValue`。

---

## 注意事项

1. **type 必须唯一**：不能与内置类型（`text`、`gauge`、`table`）或其他自定义控件重名，后注册的会覆盖先注册的。
2. **组件必须响应式**：`props.value` 会随字段数据实时更新，确保用 `computed` 或 `watch` 处理。
3. **样式用 scoped**：避免污染其他控件。
4. **尺寸自适应**：控件会被放在用户设定的宽高容器内，建议用百分比/弹性布局。
5. **不要操作 DOM**：控件外壳（拖拽、缩放、选中框）由系统管理，你的组件只负责内容渲染。
