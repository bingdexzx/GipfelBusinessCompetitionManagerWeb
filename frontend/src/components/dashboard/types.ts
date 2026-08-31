import type { Component } from "vue";
import type { FieldRef } from "@/types/dashboard";

export type BuiltinWidgetType = "text" | "gauge" | "table";

/**
 * 控件类型：内置类型（text / gauge / table）之外，允许任意自定义类型字符串。
 * 自定义类型必须经过 registerCustomWidget 注册后，仪表盘才会识别并渲染。
 */
export type WidgetType = BuiltinWidgetType | (string & {});

export interface WidgetConfig {
  id: string;
  type: WidgetType;
  x: number;
  y: number;
  /** 控件宽（px） */
  w: number;
  /** 控件高（px） */
  h: number;
  config: {
    /** 绑定的可查看字段引用（区域总览卡片 / 公司产业字段 / 消费者需求） */
    fieldRef?: FieldRef;
    /** 文字控件：绑定字段时的标题；或静态文字内容 */
    caption?: string;
    text?: string;
    /** 仪表控件 */
    label?: string;
    /** 总量：可手动填（total），或绑定字段（totalField，取值优先） */
    total?: number;
    totalField?: FieldRef;
    display?: number;
    /** 表格控件：静态字典（键/值两列）；绑定时以绑定字段的字典值为准 */
    dict?: Record<string, unknown>;
    /** 自定义控件配置：任意 JSON 可序列化对象，由对应控件组件自行解释 */
    custom?: Record<string, unknown>;
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
export interface CustomWidgetProps {
  /** 该控件在仪表盘中的完整配置（含已解析的 config.custom） */
  widget: WidgetConfig;
  /** 若用户在仪表盘绑定了「可查看字段」，这里是其当前值（字符串 / 数字 / 对象等） */
  value: unknown;
  /** 若绑定了「总量字段」，这里是其当前值 */
  totalValue: unknown;
}

/**
 * 自定义控件定义。调用 registerCustomWidget(def) 完成注册。
 */
export interface CustomWidgetDef {
  /** 控件类型标识（唯一），将作为 WidgetConfig.type 持久化到本地存储 */
  type: string;
  /** 在「添加控件」菜单中显示的名称 */
  label: string;
  /**
   * 渲染组件。必须声明 props：
   *   { widget: WidgetConfig; value: unknown; totalValue: unknown }
   * 可直接用 SFC（<script setup> 的 defineProps），或用渲染函数。
   */
  component: Component;
  /** 默认尺寸（px），创建控件时填入 w / h；缺省 220 × 160 */
  defaultSize?: { w: number; h: number };
  /**
   * 是否允许在仪表盘编辑对话框中绑定「可查看字段」。
   * true 时，对话框出现「绑定字段」下拉；组件可经 props.value 读取该字段当前值。
   * 设为 false 时，控件仅依赖 config.custom 自行取数（如自行调 API）。
   */
  bindable?: boolean;
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

/** 注册一个自定义控件。重复注册同名 type 会覆盖；与内置类型冲突会抛错。 */
export function registerCustomWidget(def: CustomWidgetDef): void {
  if (!def || !def.type) throw new Error("registerCustomWidget: def.type 必填");
  if (BUILTIN_TYPES.has(def.type))
    throw new Error(`registerCustomWidget: 类型 "${def.type}" 与内置控件冲突`);
  if (!def.label) throw new Error("registerCustomWidget: def.label 必填");
  if (!def.component) throw new Error("registerCustomWidget: def.component 必填");
  customRegistry.set(def.type, def);
}

/** 按 type 取自定义控件定义；非自定义 / 未注册返回 undefined。 */
export function getCustomWidget(type: string): CustomWidgetDef | undefined {
  return customRegistry.get(type);
}

/** 列出所有已注册的自定义控件（用于「添加控件」菜单）。 */
export function listCustomWidgets(): CustomWidgetDef[] {
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
