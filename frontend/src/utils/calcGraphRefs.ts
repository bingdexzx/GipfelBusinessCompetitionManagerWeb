/**
 * 产业计算图（calcGraph）字段引用提取 + 跨字段循环依赖检测。
 *
 * 与后端 apps/company_fields/calc.py::_graph_field_refs / _formula_field_refs
 * 及 apps/industry_types/views.py::_detect_calc_field_cycle 保持语义一致：
 * - value(FIELD) 节点：data.fieldKey 直接给出被引用字段键；
 * - value(FORMULA) 节点：data.expr（mathjs 表达式）中以变量形式出现的字段键；
 *   剔除外层字符串字面量、mathjs 保留字、以及「函数调用形态」的 EXPR_HELPERS 助手名，
 *   仅保留确属已知字段键的标识符（过滤 assign 局部变量等干扰项）。
 */
import type { GGraph, GNode } from "@/contracts/graph-model";

// mathjs 保留字（关键字 / 常量），不是字段引用
export const FORMULA_RESERVED = new Set<string>([
  "true", "false", "null", "undefined", "NaN", "Infinity",
  "and", "or", "not", "xor",
  "if", "then", "else", "elseif", "end",
  "for", "while", "do", "in", "of", "let", "const", "var",
  "function", "return", "break", "continue", "new", "this",
]);

// 与后端 apps/contracts/engine.py EXPR_HELPERS 对齐的助手函数名（函数调用形态，非字段引用）。
// 注意：以变量形式出现（如 a.keys）仍视为候选引用，仅「函数调用」形态（如 keys(x)）才排除。
export const FORMULA_HELPER_NAMES = new Set<string>([
  "IF", "AND", "OR", "NOT",
  "len", "push", "concat", "contains", "indexIn", "keys", "values",
  "get", "has", "hasKey", "merge", "unique", "flatten", "join", "sumOf",
]);

const IDENT_RE = /[A-Za-z_][A-Za-z0-9_]*/g;
const STR_DOUBLE = /"[^"]*"/g;
const STR_SINGLE = /'[^']*'/g;
const STR_BACKTICK = /`[^`]*`/g;

/** 从 FORMULA 表达式提取以变量形式引用的字段键集合。 */
export function extractFormulaFieldRefs(
  expr: string | null | undefined,
  knownKeys?: Set<string>,
): Set<string> {
  const refs = new Set<string>();
  if (!expr || !expr.trim()) return refs;
  // 去掉字符串字面量，避免引号内文本被误认为标识符
  const stripped = expr
    .replace(STR_DOUBLE, " ")
    .replace(STR_SINGLE, " ")
    .replace(STR_BACKTICK, " ");
  let m: RegExpExecArray | null;
  IDENT_RE.lastIndex = 0;
  while ((m = IDENT_RE.exec(stripped)) !== null) {
    const name = m[0];
    if (FORMULA_RESERVED.has(name)) continue;
    const after = stripped.slice(m.index + name.length).trimStart();
    if (FORMULA_HELPER_NAMES.has(name) && after.startsWith("(")) continue;
    if (knownKeys && !knownKeys.has(name)) continue;
    refs.add(name);
  }
  return refs;
}

/** 从计算图（对象或 JSON 字符串）提取其引用的全部字段键集合。 */
export function extractCalcGraphFieldRefs(
  graph: GGraph | string | null | undefined,
  knownKeys?: Set<string>,
): Set<string> {
  const refs = new Set<string>();
  if (!graph) return refs;
  let g: GGraph | null = null;
  if (typeof graph === "string") {
    const s = graph.trim();
    if (!s) return refs;
    try {
      g = JSON.parse(s) as GGraph;
    } catch {
      return refs;
    }
  } else {
    g = graph;
  }
  const nodes: GNode[] = Array.isArray(g?.nodes) ? (g!.nodes as GNode[]) : [];
  for (const n of nodes) {
    if (!n || n.type !== "value") continue;
    const d = (n.data || {}) as Record<string, any>;
    const kind = d.kind;
    if (kind === "FIELD" && d.fieldKey) {
      refs.add(String(d.fieldKey));
    } else if (kind === "FORMULA" && d.expr) {
      for (const r of extractFormulaFieldRefs(String(d.expr), knownKeys)) refs.add(r);
    }
  }
  return refs;
}

/**
 * 检测依赖图（fieldKey -> 被引用字段键列表）中的循环依赖。
 * 返回成环节点序列（如 ["a", "b", "a"]），无环返回 null。
 * 给定 focusKey 时优先返回经过它的环，便于把「当前正在编辑字段」的环提示出来。
 */
export function detectCycle(
  depMap: Record<string, string[] | Set<string>>,
  focusKey?: string,
): string[] | null {
  const WHITE = 0;
  const GRAY = 1;
  const BLACK = 2;
  const color: Record<string, number> = {};
  const stack: string[] = [];
  const cycle: string[] = [];

  function dfs(node: string): boolean {
    color[node] = GRAY;
    stack.push(node);
    const deps = depMap[node];
    if (deps) {
      for (const raw of deps) {
        const nk = typeof raw === "string" ? raw : String(raw);
        if (!(nk in depMap)) continue;
        if (color[nk] === GRAY) {
          const idx = stack.indexOf(nk);
          cycle.push(...stack.slice(idx), nk);
          return true;
        }
        if (color[nk] === WHITE && dfs(nk)) return true;
      }
    }
    color[node] = BLACK;
    stack.pop();
    return false;
  }

  for (const k of Object.keys(depMap)) color[k] = WHITE;
  // 优先从 focusKey 出发，确保返回经过当前字段的环
  if (focusKey && focusKey in depMap) {
    if (dfs(focusKey)) return cycle;
  }
  for (const k of Object.keys(depMap)) {
    if (color[k] === WHITE && dfs(k)) return cycle;
  }
  return null;
}
