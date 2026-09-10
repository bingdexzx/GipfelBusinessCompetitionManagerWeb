import type { Component } from "vue";
import { ref } from "vue";
import type { FieldRef } from "@/types/dashboard";

export type BuiltinWidgetType = "text" | "gauge" | "table";

/**
 * 控件类型：内置类型（text / gauge / table）之外，允许任意自定义类型字符串。
 * 自定义类型必须经过 registerCustomWidget 注册后，仪表盘才会识别并渲染。
 */
export type WidgetType = BuiltinWidgetType | (string & {});

export interface FieldBinding {
  /** 绑定标识（组件通过 props.values[key] 读取） */
  key: string;
  /** 字段引用 */
  fieldRef: FieldRef;
  /** 显示标签（可选，编辑弹窗中展示用） */
  label?: string;
}

export interface WidgetConfig {
  id: string;
  type: WidgetType;
  x: number;
  y: number;
  w: number;
  h: number;
  config: {
    fieldRef?: FieldRef;
    caption?: string;
    text?: string;
    label?: string;
    total?: number | string;
    totalField?: FieldRef;
    display?: number;
    dict?: Record<string, unknown>;
    custom?: Record<string, unknown>;
    /** 自定义控件多字段绑定：每个 binding 有 key + fieldRef，组件通过 props.values[key] 读取 */
    bindings?: FieldBinding[];
  };
}

// 字段引用类型已迁移到公共位置（types/dashboard），此处重新导出以保持向后兼容。
export type { FieldRef };

// ============================================================
// 自定义控件注册机制
// ============================================================

/**
 * 自定义控件组件接收的 props 契约。
 * 你的组件必须声明这三个 props（名称、类型与此一致）。
 */
export interface FieldSlot {
  key: string;
  label: string;
  required?: boolean;
}

export interface ConfigField {
  /** 配置键名，组件通过 this.widget.config.custom[key] 读取 */
  key: string;
  /** 编辑弹窗中显示的标签 */
  label: string;
  /** 输入控件类型 */
  type: "string" | "number" | "color" | "boolean" | "select";
  /** 默认值 */
  default?: unknown;
  /** type="string" 时的占位符 */
  placeholder?: string;
  /** type="number" 时的最小值 */
  min?: number;
  /** type="number" 时的最大值 */
  max?: number;
  /** type="select" 时的选项列表 */
  options?: { label: string; value: unknown }[];
}

export interface CustomWidgetProps {
  widget: WidgetConfig;
  /** 多字段绑定值：{ [fieldSlot.key]: fieldValue } */
  values: Record<string, unknown>;
}

/**
 * 自定义控件定义。调用 registerCustomWidget(def) 完成注册。
 */
export interface CustomWidgetDef {
  /** 控件类型标识（唯一），将作为 WidgetConfig.type 持久化到本地存储 */
  type: string;
  /** 在「添加控件」菜单中显示的名称 */
  label: string;
  /** 渲染组件。接收 props: { widget, values } */
  component: Component;
  /** 默认尺寸（px），创建控件时填入 w / h；缺省 220 × 160 */
  defaultSize?: { w: number; h: number };
  /**
   * 控件需要绑定的字段列表。
   * 声明后，编辑弹窗会为每个 slot 渲染一个字段选择下拉。
   * 组件通过 props.values[slot.key] 读取对应字段的实时值。
   * 不声明（或空数组）则编辑弹窗不出现字段选择。
   */
  fieldSlots?: FieldSlot[];
  /**
   * 控件可配置项列表。
   * 声明后，编辑弹窗会为每个配置项渲染对应的输入控件（文本、数字、颜色、开关、下拉），
   * 用户填写的值存储在 config.custom 中，组件通过 this.widget.config.custom[key] 读取。
   * 不声明则编辑弹窗不出现配置项。
   */
  configFields?: ConfigField[];
  /** 控件说明，显示在编辑对话框（可选） */
  description?: string;
  /**
   * 默认 custom 配置（JSON 可序列化对象），创建控件时写入 config.custom。
   * 用户可在编辑对话框的「自定义配置 (JSON)」中查看 / 修改。
   */
  defaultConfig?: Record<string, unknown>;
}

const customRegistry = new Map<string, CustomWidgetDef>();
const BUILTIN_TYPES = new Set<string>(["text", "gauge", "table"]);
// 响应式触发器：每次注册新控件时递增，使依赖 listCustomWidgets() 的 computed 重新计算
const _registryVersion = ref(0);

/** 注册一个自定义控件。重复注册同名 type 会覆盖；与内置类型冲突会抛错。 */
export function registerCustomWidget(def: CustomWidgetDef): void {
  if (!def || !def.type) throw new Error("registerCustomWidget: def.type 必填");
  if (BUILTIN_TYPES.has(def.type))
    throw new Error(`registerCustomWidget: 类型 "${def.type}" 与内置控件冲突`);
  if (!def.label) throw new Error("registerCustomWidget: def.label 必填");
  if (!def.component) throw new Error("registerCustomWidget: def.component 必填");
  customRegistry.set(def.type, def);
  _registryVersion.value++;
}

/** 按 type 取自定义控件定义；非自定义 / 未注册返回 undefined。 */
export function getCustomWidget(type: string): CustomWidgetDef | undefined {
  return customRegistry.get(type);
}

/** 列出所有已注册的自定义控件（用于「添加控件」菜单）。读取 _registryVersion 以触发响应式更新。 */
export function listCustomWidgets(): CustomWidgetDef[] {
  _registryVersion.value; // 触发 reactive 依赖收集
  return Array.from(customRegistry.values());
}

export function isBuiltinType(type: string): boolean {
  return BUILTIN_TYPES.has(type);
}

export function isCustomType(type: string): boolean {
  return customRegistry.has(type);
}

export function createWidget(type: WidgetType, index: number): WidgetConfig {
  const col = index % 4;
  const row = Math.floor(index / 4);
  const base = {
    id: `w-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    type,
    x: 60 + col * 40,
    y: 60 + row * 40,
    config: {} as WidgetConfig["config"],
  };

  // 自定义控件：使用其默认尺寸与默认配置
  const custom = getCustomWidget(type);
  if (custom) {
    return {
      ...base,
      w: custom.defaultSize?.w ?? 220,
      h: custom.defaultSize?.h ?? 160,
      config: {
        custom: custom.defaultConfig ? { ...custom.defaultConfig } : {},
      },
    };
  }

  // 内置控件
  const w = type === "gauge" ? 190 : type === "table" ? 240 : 180;
  const h = type === "gauge" ? 190 : type === "table" ? 200 : 120;
  return {
    ...base,
    w,
    h,
    config: type === "gauge" ? { total: 100, display: 0 } : {},
  };
}
