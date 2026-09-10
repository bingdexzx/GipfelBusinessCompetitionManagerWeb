# 自定义仪表盘控件开发指南

## 控件包格式

控件包是一个 **zip 文件**，包含：
```
my-widget.zip
├── manifest.json    ← 元数据
└── component.js     ← Vue 组件（Options API）
```

通过 **系统设置 → 系统管理 → 管理控件包** 上传。

---

## manifest.json

```json
{
  "type": "progress-bar",
  "label": "进度条",
  "description": "展示进度百分比",
  "version": "1.0.0",
  "fields": [
    { "key": "current", "label": "当前值字段", "required": true },
    { "key": "total", "label": "总量字段", "required": true }
  ],
  "defaultSize": { "w": 240, "h": 80 },
  "defaultConfig": {
    "title": "进度",
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
| `description` | ❌ | 控件说明 |
| `version` | ❌ | 版本号 |
| `fields` | ❌ | **字段声明列表**（见下文） |
| `defaultSize` | ❌ | 默认宽高 `{ w, h }`（px） |
| `defaultConfig` | ❌ | 默认自定义配置 |

### fields — 字段声明

`fields` 数组定义控件需要绑定哪些字段。每个元素：

```json
{ "key": "current", "label": "当前值字段", "required": true }
```

- `key`：标识名，组件通过 `this.values[key]` 读取字段值
- `label`：编辑弹窗中下拉框的标签文字
- `required`：是否必填（可选，默认 false）

声明后，编辑弹窗会**自动渲染对应数量的字段选择下拉**，用户为每个 slot 选择一个字段。不声明 `fields` 则不出现字段选择。

---

## component.js

组件用 Options API，接收 `widget` 和 `values` 两个 props：

```js
window.__widget_module__ = {
  props: ["widget", "values"],
  computed: {
    config() {
      return this.widget.config.custom || {};
    },
    // 读取绑定字段的值
    currentValue() {
      return this.values.current;  // 对应 fields 中 key: "current"
    },
    totalValue() {
      return this.values.total;    // 对应 fields 中 key: "total"
    },
  },
  template: '<div>{{ currentValue }} / {{ totalValue }}</div>',
};
```

**关键点**：
- 用 `window.__widget_module__ = { ... }` 导出（不用 `export default`）
- 用 `this.values.字段标识` 读取绑定字段的实时值
- 用 `this.widget.config.custom.配置名` 读取自定义配置
- 字段值类型：数值型为 `number`，文本型为 `string`，字典型为 `string`（JSON）或 `object`
- 未绑定时值为 `undefined`

---

## 完整示例

### 进度条（两个字段）

**manifest.json**：
```json
{
  "type": "progress-bar",
  "label": "进度条",
  "fields": [
    { "key": "current", "label": "当前值字段", "required": true },
    { "key": "total", "label": "总量字段", "required": true }
  ],
  "defaultSize": { "w": 240, "h": 80 },
  "defaultConfig": { "title": "进度", "color": "#409eff" },
  "component": "component.js"
}
```

**component.js**：
```js
window.__widget_module__ = {
  props: ["widget", "values"],
  computed: {
    config() { return this.widget.config.custom || {}; },
    current() { var v = this.values.current; return v != null ? Number(v) : 0; },
    total() { var v = this.values.total; return v != null ? Number(v) : 100; },
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

### 数据卡片（一个字段）

**manifest.json**：
```json
{
  "type": "simple-card",
  "label": "数据卡片",
  "fields": [
    { "key": "value", "label": "数据字段", "required": true }
  ],
  "defaultSize": { "w": 180, "h": 120 },
  "defaultConfig": { "title": "数据项", "color": "#1f2d3d", "bgColor": "#f0f9ff" },
  "component": "component.js"
}
```

**component.js**：
```js
window.__widget_module__ = {
  props: ["widget", "values"],
  computed: {
    config() { return this.widget.config.custom || {}; },
    displayValue() {
      var v = this.values.value;
      if (v != null && v !== "") {
        if (typeof v === "number") v = v.toLocaleString();
        return v;
      }
      return "—";
    },
  },
  template: '\
    <div :style="{ width:\'100%\',height:\'100%\',display:\'flex\',flexDirection:\'column\',alignItems:\'center\',justifyContent:\'center\',padding:\'16px\',boxSizing:\'border-box\',background:config.bgColor||\'#f0f9ff\',borderRadius:\'8px\' }">\
      <div style="font-size:12px;color:#909399;margin-bottom:8px;font-weight:500">{{ config.title }}</div>\
      <div :style="{ fontSize:\'28px\',fontWeight:\'700\',color:config.color||\'#1f2d3d\' }">{{ displayValue }}</div>\
    </div>\
  ',
};
```

---

## 使用步骤

1. 编写 `manifest.json` 和 `component.js`
2. 两个文件直接压缩为 zip（不要嵌套文件夹，直接放 zip 根目录也可）
3. 系统设置 → 系统管理 → 管理控件包 → 上传控件包
4. 页面自动刷新，仪表盘 ＋ 菜单出现新控件

---

## 无字段绑定的控件

如果控件不需要绑定字段（如自行调 API 取数据的时钟控件），不声明 `fields` 即可：

```json
{
  "type": "clock",
  "label": "时钟",
  "defaultSize": { "w": 160, "h": 80 },
  "defaultConfig": { "format": "24h" },
  "component": "component.js"
}
```

编辑弹窗只显示「自定义配置 (JSON)」，不显示字段选择。

---

## 注意事项

1. **type 必须唯一**：不能与内置类型或其他控件包重名
2. **用 Options API**：不能用 `<script setup>`，只能用 `export default { props, computed, template }`
3. **template 中的引号**：template 是字符串，内部引号需要转义
4. **不要用 import**：component.js 是独立模块，不能 import 其他文件
5. **更新控件包**：上传同 type 的新 zip 自动替换旧版
6. **示例控件包**：`widget-package-examples/` 目录下有 progress-bar 和 simple-card 两个完整示例
