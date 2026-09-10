# 自定义仪表盘控件开发指南

## 一、控件包方式（推荐）

### 什么是控件包

控件包是一个 **zip 文件**，包含：
```
my-widget.zip
├── manifest.json    ← 元数据（名称、描述、默认配置等）
└── component.js     ← Vue 组件代码（ES module）
```

通过系统设置 → 后端管理 →「管理控件包」上传，即刻生效。

---

### manifest.json 格式

```json
{
  "type": "my-widget",
  "label": "我的控件",
  "description": "控件说明，显示在管理界面和编辑弹窗",
  "version": "1.0.0",
  "bindable": true,
  "defaultSize": { "w": 200, "h": 150 },
  "defaultConfig": {
    "title": "默认标题",
    "color": "#409eff"
  },
  "component": "component.js"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | ✅ | 唯一标识（英文），不能与内置类型(text/gauge/table)重名 |
| `label` | ✅ | 「添加控件」菜单中显示的名称 |
| `component` | ❌ | 组件文件名，默认 `component.js` |
| `description` | ❌ | 控件说明文字 |
| `version` | ❌ | 版本号，默认 `1.0.0` |
| `bindable` | ❌ | 是否允许绑定字段（默认 `true`） |
| `defaultSize` | ❌ | 默认宽高 `{ w, h }`（px），默认 `220×160` |
| `defaultConfig` | ❌ | 默认自定义配置对象 |

---

### component.js 格式

组件必须将 Vue 组件对象赋值给 window.__widget_module__（不用 export default），接收三个 props：

| Prop | 类型 | 说明 |
|------|------|------|
| `widget` | `object` | 控件完整配置（位置、尺寸、`widget.config.custom` 等） |
| `value` | `any` | 绑定字段的当前值（未绑定时为 `undefined`） |
| `totalValue` | `any` | 绑定的总量字段的当前值（未绑定时为 `undefined`） |

**示例：数据卡片**

```js
window.__widget_module__ = {
  props: ["widget", "value", "totalValue"],
  computed: {
    config() {
      return (this.widget.config.custom || {});
    },
    title() {
      return this.config.title || "";
    },
    displayValue() {
      if (this.value != null) return this.value;
      return this.config.defaultValue || "—";
    },
  },
  template: '\
    <div style="width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px">\
      <div style="font-size:12px;color:#909399;margin-bottom:8px">{{ title }}</div>\
      <div style="font-size:28px;font-weight:700;color:#1f2d3d">{{ displayValue }}</div>\
    </div>\
  ',
};
```

**示例：进度条**

```js
window.__widget_module__ = {
  props: ["widget", "value", "totalValue"],
  computed: {
    config() { return (this.widget.config.custom || {}); },
    current() {
      return this.value != null ? Number(this.value) : Number(this.config.current || 0);
    },
    total() {
      return this.totalValue != null ? Number(this.totalValue) : Number(this.config.total || 100);
    },
    pct() {
      if (!this.total || this.total <= 0) return 0;
      return Math.min(100, Math.round((this.current / this.total) * 100));
    },
  },
  template: '\
    <div style="width:100%;height:100%;display:flex;flex-direction:column;justify-content:center;padding:14px 16px;box-sizing:border-box;gap:8px">\
      <div v-if="config.title" style="font-size:12px;color:#909399">{{ config.title }}</div>\
      <div style="height:12px;background:#ebeef5;border-radius:6px;overflow:hidden">\
        <div :style="{ width: pct+\'%\', background: config.color||\'#409eff\', height:\'100%\', borderRadius:\'6px\' }"></div>\
      </div>\
      <div style="font-size:12px;color:#606266;text-align:right">{{ current }} / {{ total }} ({{ pct }}%)</div>\
    </div>\
  ',
};
```

---

### 使用步骤

1. **编写** `manifest.json` 和 `component.js`
2. **打包**：选中两个文件 → 右键 → 压缩为 zip（zip 根目录直接包含这两个文件，不要嵌套文件夹）
3. **上传**：系统设置 → 后端管理 → 管理控件包 → 上传控件包
4. **使用**：仪表盘 → 点击 ＋ → 选择你的控件

上传后刷新页面即可在仪表盘看到新控件。

---

### 注意事项

1. **template 中的引号**：因为 `component.js` 用字符串定义 template，内部引号需要转义，建议用单引号包裹 template，内部用双引号；或用反斜杠转义。
2. **不要用 `<script setup>`**：控件包的 component.js 是运行时加载的，不经过编译，只能用 Options API（`window.__widget_module__ = { props, computed, template }`）。
3. **不要用 `import`**：component.js 是独立模块，不能 import 其他 .vue 文件。需要的功能请内联实现。
4. **单文件组件不支持**：不能用 `.vue` 文件，只能用纯 JS + template 字符串。
5. **更新控件包**：上传同 `type` 的新 zip 会自动替换旧版本。
6. **启停控制**：可以在管理界面停用某个控件包（不删除，只是不加载）。

---

### 示例控件包

项目 `widget-package-examples/` 目录下有两个完整示例：

- `progress-bar/` — 进度条控件
- `simple-card/` — 数据卡片控件

打包方法：
```bash
cd widget-package-examples/progress-bar
zip ../progress-bar.zip manifest.json component.js
```

然后在管理界面上传 `progress-bar.zip` 即可。

---

## 二、代码内注册方式（开发者）

如果你有前端开发能力，也可以直接在代码中注册控件：

### 第一步：创建组件

`frontend/src/components/dashboard/widgets/MyWidget.vue`：

```vue
<template>
  <div class="my-widget">
    <div class="my-title">{{ config.title }}</div>
    <div class="my-value">{{ displayValue }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { CustomWidgetProps } from "../types";

const props = defineProps<CustomWidgetProps>();
const config = computed(() => (props.widget.config.custom || {}) as Record<string, unknown>);
const displayValue = computed(() => props.value ?? config.value.defaultValue ?? "—");
</script>

<style scoped>
.my-widget {
  width: 100%; height: 100%;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 12px; box-sizing: border-box;
}
.my-title { font-size: 12px; color: #909399; margin-bottom: 8px; }
.my-value { font-size: 24px; font-weight: 700; color: #1f2d3d; }
</style>
```

### 第二步：注册

编辑 `frontend/src/components/dashboard/registerCustomWidgets.ts`：

```typescript
import { registerCustomWidget } from "./types";
import MyWidget from "./widgets/MyWidget.vue";

registerCustomWidget({
  type: "my-widget",
  label: "我的控件",
  component: MyWidget,
  bindable: true,
  description: "一个示例控件",
  defaultSize: { w: 200, h: 150 },
  defaultConfig: { title: "示例", defaultValue: 0 },
});
```

### 第三步：构建

```bash
cd frontend && npm run build
```

---

## 三、附录

### WidgetConfig 完整结构

```typescript
interface WidgetConfig {
  id: string;          // 自动生成
  type: string;        // 控件类型标识
  x: number;           // 左上角 X (px)
  y: number;           // 左上角 Y (px)
  w: number;           // 宽度 (px)
  h: number;           // 高度 (px)
  config: {
    fieldRef?: FieldRef;           // 绑定的字段引用
    caption?: string;              // 标题
    totalField?: FieldRef;         // 总量字段引用
    custom?: Record<string, unknown>;  // ← 自定义配置在这里
  };
}
```

### 字段值类型

`props.value` 的类型取决于绑定的字段：
- **数值型字段**：`number` 或 `string`（大数安全时为字符串）
- **文本型字段**：`string`
- **字典型字段**：`string`（JSON 字符串，需 `JSON.parse`）或 `object`
- **未绑定**：`undefined`

建议统一用 `computed` 处理类型转换，避免直接假设类型。
