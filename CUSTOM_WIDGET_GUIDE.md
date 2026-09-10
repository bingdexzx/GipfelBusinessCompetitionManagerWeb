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
  "configFields": [
    { "key": "title", "label": "标题", "type": "string", "default": "进度" },
    { "key": "color", "label": "颜色", "type": "color", "default": "#409eff" },
    { "key": "showPercent", "label": "显示百分比", "type": "boolean", "default": true }
  ],
  "defaultSize": { "w": 240, "h": 80 },
  "component": "component.js"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | ✅ | 唯一标识（英文） |
| `label` | ✅ | 菜单中显示的名称 |
| `component` | ❌ | 组件文件名，默认 `component.js` |
| `description` | ❌ | 控件说明 |
| `version` | ❌ | 版本号 |
| `fields` | ❌ | 字段绑定声明（见下文） |
| `configFields` | ❌ | 可配置项声明（见下文） |
| `defaultSize` | ❌ | 默认宽高 `{ w, h }`（px） |

### fields — 字段绑定

定义控件需要绑定哪些字段。编辑弹窗为每个字段渲染一个下拉选择框。

```json
{ "key": "current", "label": "当前值字段", "required": true }
```

- `key`：标识名，组件通过 `this.values[key]` 读取
- `label`：下拉框标签
- `required`：是否必填（可选）

### configFields — 可配置项

定义用户可以在编辑弹窗中填写的配置项（标题、颜色、数字等），编辑弹窗自动渲染对应的输入控件。

```json
{ "key": "title", "label": "标题", "type": "string", "default": "进度", "placeholder": "输入标题" }
```

| type | 渲染控件 | 说明 |
|------|---------|------|
| `string` | 文本输入框 | 支持 placeholder |
| `number` | 数字输入框 | 支持 min / max |
| `color` | 颜色选择器 | |
| `boolean` | 开关 | |
| `select` | 下拉选择 | 需要 `options: [{ label, value }]` |

可选属性：`default`（默认值）、`placeholder`、`min`、`max`、`options`。

---

## component.js

```js
window.__widget_module__ = {
  props: ["widget", "values"],
  computed: {
    // 读取配置项
    config() { return this.widget.config.custom || {}; },
    title() { return this.config.title || ""; },
    color() { return this.config.color || "#409eff"; },
    // 读取绑定字段
    currentValue() { return this.values.current; },
    totalValue() { return this.values.total; },
  },
  template: '<div :style="{ color: color }">{{ title }}: {{ currentValue }}</div>',
};
```

- `this.values.字段标识` — 读取绑定字段的实时值
- `this.widget.config.custom.配置键` — 读取用户填写的配置项

---

## 完整示例

### 进度条（两个字段 + 两个配置项）

**manifest.json**：
```json
{
  "type": "progress-bar",
  "label": "进度条",
  "fields": [
    { "key": "current", "label": "当前值字段", "required": true },
    { "key": "total", "label": "总量字段", "required": true }
  ],
  "configFields": [
    { "key": "title", "label": "标题", "type": "string", "default": "进度", "placeholder": "显示在进度条上方" },
    { "key": "color", "label": "颜色", "type": "color", "default": "#409eff" }
  ],
  "defaultSize": { "w": 240, "h": 80 },
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

---

## 使用步骤

1. 编写 `manifest.json` 和 `component.js`
2. 压缩为 zip
3. 系统设置 → 系统管理 → 管理控件包 → 上传
4. 页面自动刷新，仪表盘 ＋ 菜单出现新控件

---

## 无字段绑定的控件

不需要绑定字段的控件（如时钟），不声明 `fields` 即可，只用 `configFields` 提供配置项：

```json
{
  "type": "clock",
  "label": "时钟",
  "configFields": [
    { "key": "format", "label": "格式", "type": "select", "default": "24h",
      "options": [{ "label": "24小时", "value": "24h" }, { "label": "12小时", "value": "12h" }] }
  ],
  "defaultSize": { "w": 160, "h": 80 },
  "component": "component.js"
}
```

---

## 注意事项

1. **type 必须唯一**：不能与内置类型或其他控件包重名
2. **用 Options API**：`window.__widget_module__ = { props, computed, template }`
3. **template 中的引号**：内部引号需要转义（用 `\'` ）
4. **不要用 import**：component.js 是独立模块
5. **更新控件包**：上传同 type 的新 zip 自动替换旧版
6. **示例**：`widget-package-examples/` 目录下有 progress-bar 和 simple-card
