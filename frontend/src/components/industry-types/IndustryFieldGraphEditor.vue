<template>
  <div class="ge">
    <!-- 顶部工具栏 -->
    <div class="ge-toolbar">
      <el-button @click="$emit('close')">返回</el-button>
      <el-button @click="toggleSource">{{ showSource ? "画布视图" : "源码 JSON" }}</el-button>
      <el-button @click="applyAutoLayout" title="自动分层排列节点">自动布局</el-button>
      <el-button type="danger" @click="onClear">清空</el-button>
      <el-button-group class="ge-zoom">
        <el-button size="small" title="缩小" @click="zoomOut">－</el-button>
        <el-button size="small" title="重置视图(100%)" @click="resetView"
          >{{ Math.round(zoom * 100) }}%</el-button
        >
        <el-button size="small" title="放大" @click="zoomIn">＋</el-button>
        <el-button size="small" title="适应全部内容" @click="fitView(svgW, svgH)">适应</el-button>
      </el-button-group>
      <el-button size="small" title="搜索节点 (Ctrl+F)" @click="toggleSearch">🔍</el-button>
      <div v-if="searchVisible" class="ge-search-bar">
        <el-input
          v-model="searchQuery"
          size="small"
          placeholder="搜索节点..."
          class="ge-search-input"
          clearable
          @keydown="onSearchKeydown"
        />
        <span class="ge-search-count" v-if="searchQuery.trim()">
          {{ searchMatchIds.size }} 个匹配
        </span>
      </div>
      <span v-if="pending" class="ge-connecting"
        >已选输出端口，请点击目标输入端口连线（再次点输出端口取消）</span
      >
      <span v-else class="ge-hint"
        >拖动节点标题移动；点输出端口→点输入端口连线；点连线可删除</span
      >
    </div>

    <div class="ge-body">
      <!-- 左侧节点库 -->
      <div class="ge-palette">
        <div class="ge-palette-title">节点库</div>
        <div v-for="cat in palette" :key="cat.group" class="ge-palette-group">
          <div class="ge-palette-group-title">{{ cat.group }}</div>
          <div
            v-for="item in cat.items"
            :key="item.type"
            class="ge-palette-item"
            :style="{ borderLeftColor: NODE_META[item.type].color }"
            @click="addNode(item.type)"
          >
            + {{ item.title }}
          </div>
        </div>
      </div>

      <!-- 中间画布 -->
      <div
        ref="canvasRef"
        class="ge-canvas"
        @mousedown="onCanvasDown"
        @wheel.prevent="onWheel"
        :style="{ backgroundPosition: panX + 'px ' + panY + 'px' }"
      >
        <!-- 视口层：缩放/平移只作用于此 transform，世界坐标(node.x/svgW 等)保持不变 -->
        <div class="ge-viewport" :style="viewportStyle">
        <svg class="ge-svg" :width="svgW" :height="svgH">
          <path
            v-for="e in visibleEdges"
            :key="e.id"
            :d="edgePath(e) || ''"
            class="ge-edge"
            @click.stop="removeEdge(e.id)"
          >
            <title>点击删除连线</title>
          </path>
        </svg>

        <div
          v-for="n in visibleNodes"
          :key="n.id"
          class="ge-node"
          :class="{
            'ge-node-sel': n.id === selectedId,
            'ge-node-match': isNodeMatched(n.id),
            'ge-node-dim': isNodeDimmed(n.id),
          }"
          :style="nodeStyle(n)"
          @click.stop="select(n.id)"
        >
          <div
            class="ge-node-header"
            :style="{ background: NODE_META[n.type].color }"
            @mousedown.stop.prevent="startDrag(n, $event)"
          >
            <span>
              <span
                v-if="n.type === 'if'"
                class="ge-fold-btn"
                @click.stop="toggleCollapse(n.id)"
              >{{ isCollapsed(n.id) ? '▶' : '▼' }}</span>
              {{ NODE_META[n.type].title }}
            </span>
            <span v-if="n.type !== 'output'" class="ge-node-del" @click.stop="removeNode(n.id)"
              >✕</span
            >
          </div>
          <div v-if="isCollapsed(n.id)" class="ge-collapse-badge">
            {{ hiddenChildCount(n.id) }} 个节点已隐藏
          </div>
          <div class="ge-node-cap">{{ nodeSummary(n) }}</div>

          <!-- 输入端口 + 名称 + 类型 -->
          <template v-for="(h, i) in indInputHandles(n)" :key="'i' + h">
            <div
              class="ge-port ge-port-in"
              :class="{ 'ge-port-hot': pending }"
              :style="portStyle('in', i)"
              :title="portTitle(n, 'in', i)"
              @mousedown.stop
              @click.stop="onPortClick(n.id, h, 'in')"
            ></div>
            <div class="ge-port-info" :style="infoStyle('in', i)">
              <div class="ge-port-row">
                <span class="ge-port-name">{{ indPortLabel(n, 'in', i) }}</span>
                <span class="ge-port-type">{{ indPortType(n, 'in', i) }}</span>
              </div>
            </div>
          </template>

          <!-- 输出端口 + 名称 + 类型（右栏，镜像） -->
          <template v-for="(h, j) in indOutputHandles(n)" :key="'o' + h">
            <div class="ge-port-info ge-port-info-out" :style="infoStyle('out', j)">
              <div class="ge-port-row">
                <span class="ge-port-name">{{ indPortLabel(n, 'out', j) }}</span>
                <span class="ge-port-type">{{ indPortType(n, 'out', j) }}</span>
              </div>
            </div>
            <div
              class="ge-port ge-port-out"
              :class="{ 'ge-port-hot': pending && pending.nodeId === n.id }"
              :style="portStyle('out', j)"
              :title="portTitle(n, 'out', j)"
              @mousedown.stop
              @click.stop="onPortClick(n.id, h, 'out')"
            ></div>
          </template>
        </div>
        </div>
      </div>

      <!-- 右侧属性面板 -->
      <div class="ge-panel">
        <el-alert
          v-if="warnings.length"
          type="warning"
          :closable="false"
          show-icon
          class="ge-warn"
          title="当前图尚不完整"
          :description="warnings.join('；')"
        />

        <template v-if="selectedNode">
          <div class="ge-sel-title">
            {{ NODE_META[selectedNode.type].title }}
            <el-button
              v-if="selectedNode.type !== 'output'"
              size="small"
              type="danger"
              plain
              @click="removeNode(selectedNode.id)"
              >删除</el-button
            >
          </div>
          <el-divider />

          <!-- 输出节点 -->
          <template v-if="selectedNode.type === 'output'">
            <div class="ge-tip">
              本节点是计算结果汇点：把最终表达式连到左侧「值」端口即可。保存后，该表达式的求值结果即写入本计算字段（不会回写其它字段）。
            </div>
          </template>

          <!-- 数值源 -->
          <template v-else-if="selectedNode.type === 'value'">
            <el-form label-width="80px" size="small">
              <el-form-item label="来源">
                <el-select
                  v-model="selectedNode.data.kind"
                  style="width: 100%"
                  @change="onKindChange"
                >
                  <el-option
                    v-for="t in IND_VALUE_KINDS"
                    :key="t"
                    :label="IND_VALUE_KIND_LABEL[t] || t"
                    :value="t"
                  />
                </el-select>
              </el-form-item>

              <template v-if="selectedNode.data.kind === 'FIELD'">
                <el-form-item label="产业字段">
                  <el-select
                    v-model="selectedNode.data.fieldKey"
                    placeholder="选择字段"
                    clearable
                    filterable
                    allow-create
                    default-first-option
                    style="width: 100%"
                  >
                    <el-option
                      v-for="f in fieldOptions"
                      :key="f.value"
                      :label="f.label"
                      :value="f.value"
                    />
                  </el-select>
                </el-form-item>
                <div class="ge-tip">
                  读取本产业类型中该字段的当前值（按字段键匹配）。数字字段返回数字，列表/字典字段返回数组/对象。把本节点的「输出」连到运算/条件/输出节点即可参与计算。
                </div>
              </template>

              <template v-else-if="selectedNode.data.kind === 'CONST'">
                <el-form-item label="常量值">
                  <el-input v-model="selectedNode.data.value" placeholder="数字或 JSON" />
                </el-form-item>
                <div class="ge-tip">
                  快捷填入：
                  <el-button size="small" link type="primary" @click="setConstEmpty('dict')"
                    >空字典 {}</el-button
                  >
                  <el-button size="small" link type="primary" @click="setConstEmpty('list')"
                    >空数组 []</el-button
                  >
                </div>
              </template>

              <template v-else-if="selectedNode.data.kind === 'FORMULA'">
                <el-form-item label="公式">
                  <div class="ge-formula-editor">
                    <textarea
                      class="ge-formula-textarea"
                      :class="{ 'ge-formula-error': formulaValidationError }"
                      :value="selectedNode.data.expr"
                      @input="onFormulaInput($event, selectedNode.data)"
                      @keydown="onFormulaKeydown($event, selectedNode.data)"
                      placeholder="mathjs 表达式，变量=字段键&#10;Ctrl+Space 触发自动补全"
                      spellcheck="false"
                    ></textarea>
                    <div v-if="formulaValidationError" class="ge-formula-error-msg">
                      {{ formulaValidationError }}
                    </div>
                  </div>
                </el-form-item>
                <div class="ge-formula-hints">
                  <div class="ge-formula-hint-title">可用变量（字段键）：
                    <code v-for="k in getFormulaFieldKeys()" :key="k" class="ge-formula-key">{{ k }}</code>
                    <span v-if="!getFormulaFieldKeys().length" class="ge-tip-inline">暂无字段</span>
                  </div>
                  <div class="ge-formula-hint-title">函数：
                    <code v-for="f in formulaFunctions" :key="f.key" class="ge-formula-fn" :title="f.desc">{{ f.label }}</code>
                  </div>
                  <div class="ge-tip" style="margin-top:4px">作用域还内置 EXPR_HELPERS 辅助函数。</div>
                </div>
                <!-- 自动补全下拉 -->
                <Teleport to="body">
                  <div
                    v-if="formulaAutocomplete.show"
                    class="ge-formula-autocomplete"
                    :style="{ left: formulaAutocomplete.x + 'px', top: formulaAutocomplete.y + 'px' }"
                  >
                    <div
                      v-for="item in formulaAutocomplete.items"
                      :key="item"
                      class="ge-formula-ac-item"
                      @mousedown.prevent="insertFormulaCompletion(item, selectedNode.data)"
                    >
                      {{ item }}
                    </div>
                  </div>
                </Teleport>
              </template>

              <template v-else-if="selectedNode.data.kind === 'OP'">
                <el-form-item label="运算">
                  <el-select
                    v-model="selectedNode.data.op"
                    style="width: 100%"
                    @change="onOpChange"
                  >
                    <el-option-group label="算术">
                      <el-option
                        v-for="o in IND_ARITH_OPS"
                        :key="o"
                        :label="OP_LABELS_FULL[o] || o"
                        :value="o"
                      />
                    </el-option-group>
                    <el-option-group label="布尔比较">
                      <el-option
                        v-for="o in IND_BOOL_OPS"
                        :key="o"
                        :label="OP_LABELS_FULL[o] || o"
                        :value="o"
                      />
                    </el-option-group>
                    <el-option-group label="列表">
                      <el-option
                        v-for="o in IND_LIST_OPS"
                        :key="o"
                        :label="OP_LABELS_FULL[o] || o"
                        :value="o"
                      />
                    </el-option-group>
                    <el-option-group label="字典">
                      <el-option
                        v-for="o in IND_DICT_OPS"
                        :key="o"
                        :label="OP_LABELS_FULL[o] || o"
                        :value="o"
                      />
                    </el-option-group>
                  </el-select>
                </el-form-item>
                <el-form-item
                  v-for="h in opArgs"
                  :key="h"
                  :label="OP_ARG_LABELS[h] || h"
                >
                  <el-input
                    v-model="selectedNode.data.argLiterals[h]"
                    placeholder="字面量(可选)"
                  />
                </el-form-item>
                <div class="ge-tip">
                  把各参数输入端口连到数值/运算节点；未连线的参数取上方字面量。输出连到下游数值/条件/输出节点。
                </div>
              </template>

              <template v-else-if="selectedNode.data.kind === 'VAR'">
                <el-form-item label="变量名">
                  <el-input v-model="selectedNode.data.name" placeholder="如 tmp" />
                </el-form-item>
                <div class="ge-tip">
                  读取由「赋值」节点写入的运行期变量（不回写字段）。变量名须与某个「赋值」节点的名称一致。
                </div>
              </template>

              <template v-else-if="selectedNode.data.kind === 'CONSUMER_DEMAND'">
                <div class="ge-tip">
                  自动读取本产业实例（公司）「所在地」字段对应的地图节点，取该节点所属区域，汇总本比赛该区域下全部消费者需求（ConsumerDemand.quantity）之和。无需额外参数；所在地为空或找不到区域时返回 0。把本节点的「输出」连到运算 / 条件 / 输出节点即可参与计算。
                </div>
              </template>
            </el-form>
          </template>

          <!-- 条件 IF -->
          <template v-else-if="selectedNode.type === 'if'">
            <div class="ge-tip">
              值返回式条件分支：把「条件」端口连到一个布尔/数值节点；「真分支值」「假分支值」分别连到两个数值节点。求值时先算条件，为真取真分支值、为假取假分支值，再从本节点的「结果」输出连到下游数值/运算/输出节点。
            </div>
          </template>

          <!-- 赋值 -->
          <template v-else-if="selectedNode.type === 'assign'">
            <el-form label-width="80px" size="small">
              <el-form-item label="变量名">
                <el-input v-model="selectedNode.data.name" placeholder="如 tmp" />
              </el-form-item>
            </el-form>
            <div class="ge-tip">
              把「值」端口连到一个数值节点；求值时该值存入运行期变量（变量名见上），供后续「数值源·运行期变量」引用。赋值不回写任何字段。
            </div>
          </template>
        </template>
        <div v-else class="ge-sel-empty">点击画布中的节点查看 / 编辑属性</div>

        <template v-if="showSource">
          <el-divider />
          <div class="ge-source-title">源码 JSON（保存时以此生成）</div>
          <pre class="json-box">{{ sourceJson }}</pre>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onUnmounted, nextTick } from "vue";
import { ElMessage } from "element-plus";
import { useGraphViewport } from "@/composables/useGraphViewport";
import {
  GGraph,
  GNode,
  GNodeType,
  NODE_META,
  OP_ARG_SPECS,
  OP_LABELS_FULL,
  OP_ARG_LABELS,
  ARITH_OPS,
} from "@/contracts/graph-model";

const props = defineProps<{
  modelValue?: string | null;
  availableFields?: { fieldKey: string; name?: string; fieldType?: string }[];
}>();
const emit = defineEmits<{
  (e: "close"): void;
  (e: "update:modelValue", v: string): void;
}>();

// ===== 几何常量（与合同可视化编辑器一致） =====
const NODE_W = 288;
const COL_W = 118;
const HEADER_H = 30;
const PORT_TOP = 20;
const PORT_GAP = 50;
const DOT = 12;
const PORT_INSET = 12;

// ===== 产业计算图专用节点端口（局部定义，避免影响合同编辑器） =====
// value 节点：输出恒为 "out"；输入端口依 kind 动态决定。
function indInputHandles(node: GNode): string[] {
  if (node.type === "output") return ["value"];
  if (node.type === "assign") return ["value"];
  if (node.type === "if") return ["cond", "then", "else"];
  if (node.type === "value") {
    const k = node.data?.kind as string;
    if (k === "OP") return OP_ARG_SPECS[node.data?.op as string] || [];
    return [];
  }
  return [];
}
function indOutputHandles(node: GNode): string[] {
  if (node.type === "value") return ["out"];
  if (node.type === "if") return ["out"];
  return [];
}

const IND_PORT_LABEL: Record<string, string> = {
  value: "值",
  cond: "条件",
  then: "真分支值",
  else: "假分支值",
  out: "结果",
};
function indPortLabel(node: GNode, kind: "in" | "out", idx: number): string {
  const list = kind === "in" ? indInputHandles(node) : indOutputHandles(node);
  const handle = list[idx] || "";
  if (node.type === "value" && kind === "in") return OP_ARG_LABELS[handle] || handle;
  return IND_PORT_LABEL[handle] || (handle === "out" ? "输出" : handle);
}
function indPortType(node: GNode, kind: "in" | "out", idx: number): string {
  const list = kind === "in" ? indInputHandles(node) : indOutputHandles(node);
  const handle = list[idx] || "";
  if (node.type === "output") return "结果";
  if (node.type === "if" && handle === "cond") return "布尔";
  if (node.type === "value" && kind === "out") return "值";
  return "值";
}

// ===== 图状态 =====
const graph = reactive<GGraph>({ nodes: [], edges: [] });
const selectedId = ref<string | null>(null);
const pending = ref<{ nodeId: string; handle: string } | null>(null);
const showSource = ref(false);
// 画布缩放 / 平移（共享 composable）：空白处拖拽平移、滚轮以鼠标为中心缩放。
const { zoom, panX, panY, canvasRef, viewportStyle, onWheel, startPan, zoomIn, zoomOut, fitView, resetView } =
  useGraphViewport();

// ===== 搜索/查找 =====
const searchQuery = ref("");
const searchVisible = ref(false);
const searchMatchIds = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return new Set<string>();
  return new Set(
    graph.nodes
      .filter((n) => {
        const summary = nodeSummary(n).toLowerCase();
        const label = (n.data?.label || "").toLowerCase();
        const key = (n.data?.key || "").toLowerCase();
        const name = (n.data?.name || "").toLowerCase();
        return summary.includes(q) || label.includes(q) || key.includes(q) || name.includes(q);
      })
      .map((n) => n.id),
  );
});
function onSearchKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && searchMatchIds.value.size > 0) {
    const firstId = [...searchMatchIds.value][0];
    const node = graph.nodes.find((n) => n.id === firstId);
    if (node) {
      select(firstId);
      centerOnNode(node);
    }
  }
  if (e.key === "Escape") {
    searchVisible.value = false;
    searchQuery.value = "";
  }
}
function centerOnNode(node: GNode) {
  const rect = canvasRef.value?.getBoundingClientRect();
  if (!rect) return;
  const targetX = node.x + NODE_W / 2;
  const targetY = node.y + 60;
  panX.value = rect.width / 2 - targetX * zoom.value;
  panY.value = rect.height / 2 - targetY * zoom.value;
}
function toggleSearch() {
  searchVisible.value = !searchVisible.value;
  if (searchVisible.value) {
    nextTick(() => {
      const el = document.querySelector(".ge-search-input input") as HTMLInputElement;
      if (el) el.focus();
    });
  } else {
    searchQuery.value = "";
  }
}
function isNodeMatched(nodeId: string): boolean {
  return searchQuery.value.trim() !== "" && searchMatchIds.value.has(nodeId);
}
function isNodeDimmed(nodeId: string): boolean {
  return searchQuery.value.trim() !== "" && !searchMatchIds.value.has(nodeId);
}

// ===== 折叠/展开（IF 节点） =====
const collapsedNodes = reactive(new Set<string>());
function toggleCollapse(nodeId: string) {
  if (collapsedNodes.has(nodeId)) collapsedNodes.delete(nodeId);
  else collapsedNodes.add(nodeId);
}
function isCollapsed(nodeId: string): boolean {
  return collapsedNodes.has(nodeId);
}
function hiddenChildCount(nodeId: string): number {
  const visited = new Set<string>();
  const queue: string[] = [nodeId];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const e of graph.edges) {
      if (e.source === cur && (e.sourceHandle === "then" || e.sourceHandle === "else")) {
        if (!visited.has(e.target)) {
          visited.add(e.target);
          queue.push(e.target);
        }
      }
    }
  }
  return visited.size;
}
function isHiddenByFold(nodeId: string): boolean {
  let cur = nodeId;
  const visited = new Set<string>();
  while (cur) {
    if (visited.has(cur)) break;
    visited.add(cur);
    const parentEdge = graph.edges.find((e) => e.target === cur && e.targetHandle === "parent");
    if (!parentEdge) break;
    if (collapsedNodes.has(parentEdge.source)) return true;
    cur = parentEdge.source;
  }
  return false;
}
function isEdgeHiddenByFold(edge: any): boolean {
  return isHiddenByFold(edge.source) || isHiddenByFold(edge.target);
}
const visibleNodes = computed(() => graph.nodes.filter((n) => !isHiddenByFold(n.id)));
const visibleEdges = computed(() => graph.edges.filter((e) => !isEdgeHiddenByFold(e)));

// ===== 自动布局（分层布局） =====
function applyAutoLayout() {
  const nodes = graph.nodes;
  if (!nodes.length) return;
  const children = new Map<string, string[]>();
  const parents = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (!children.has(e.source)) children.set(e.source, []);
    children.get(e.source)!.push(e.target);
    if (!parents.has(e.target)) parents.set(e.target, []);
    parents.get(e.target)!.push(e.source);
  }
  const levels = new Map<string, number>();
  const queue: string[] = [];
  for (const n of nodes) {
    if (n.type === "output" || !parents.has(n.id)) {
      levels.set(n.id, 0);
      queue.push(n.id);
    }
  }
  while (queue.length) {
    const curId = queue.shift()!;
    const curLevel = levels.get(curId)!;
    for (const childId of children.get(curId) || []) {
      const newLevel = curLevel + 1;
      if (!levels.has(childId) || levels.get(childId)! < newLevel) {
        levels.set(childId, newLevel);
        queue.push(childId);
      }
    }
  }
  for (const n of nodes) {
    if (!levels.has(n.id)) levels.set(n.id, 1);
  }
  const levelGroups = new Map<number, GNode[]>();
  for (const n of nodes) {
    const lv = levels.get(n.id)!;
    if (!levelGroups.has(lv)) levelGroups.set(lv, []);
    levelGroups.get(lv)!.push(n);
  }
  const COL_GAP = 280;
  const ROW_GAP = 140;
  const sortedLevels = [...levelGroups.keys()].sort((a, b) => a - b);
  for (const lv of sortedLevels) {
    const group = levelGroups.get(lv)!;
    group.forEach((n, i) => {
      n.x = 40 + lv * COL_GAP;
      n.y = 40 + i * ROW_GAP;
    });
  }
}
function onGlobalKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === "f") {
    e.preventDefault();
    toggleSearch();
  }
}
// ===== FORMULA 编辑增强 =====
const formulaFunctions = [
  { key: "round", label: "round()", desc: "四舍五入" },
  { key: "max", label: "max()", desc: "最大值" },
  { key: "min", label: "min()", desc: "最小值" },
  { key: "abs", label: "abs()", desc: "绝对值" },
  { key: "ceil", label: "ceil()", desc: "向上取整" },
  { key: "floor", label: "floor()", desc: "向下取整" },
  { key: "sqrt", label: "sqrt()", desc: "平方根" },
  { key: "log", label: "log()", desc: "对数" },
  { key: "exp", label: "exp()", desc: "指数" },
  { key: "pow", label: "pow()", desc: "幂运算" },
];
const formulaAutocomplete = ref<{ show: boolean; items: string[]; x: number; y: number }>({
  show: false,
  items: [],
  x: 0,
  y: 0,
});
const formulaValidationError = ref<string>("");
function getFormulaFieldKeys(): string[] {
  return (props.availableFields || []).map((f) => f.fieldKey).filter(Boolean);
}
function validateFormulaExpr(expr: string): string {
  if (!expr || !expr.trim()) return "";
  let depth = 0;
  let inStr = false;
  let strChar = "";
  for (const ch of expr) {
    if (inStr) {
      if (ch === strChar) inStr = false;
      continue;
    }
    if (ch === '"' || ch === "'") {
      inStr = true;
      strChar = ch;
      continue;
    }
    if (ch === "(" || ch === "[") depth++;
    if (ch === ")" || ch === "]") {
      depth--;
      if (depth < 0) return "括号不匹配：多余的关闭括号";
    }
  }
  if (depth > 0) return "括号不匹配：缺少关闭括号";
  if (inStr) return "引号不匹配：缺少关闭引号";
  return "";
}
function onFormulaInput(e: Event, nodeData: any) {
  const val = (e.target as HTMLTextAreaElement).value;
  nodeData.expr = val;
  formulaValidationError.value = validateFormulaExpr(val);
}
function onFormulaKeydown(e: KeyboardEvent, nodeData: any) {
  if ((e.ctrlKey || e.metaKey) && e.key === " ") {
    e.preventDefault();
    showFormulaAutocomplete(e.target as HTMLTextAreaElement, nodeData);
  }
}
function showFormulaAutocomplete(ta: HTMLTextAreaElement, nodeData: any) {
  const val = ta.value;
  const cursorPos = ta.selectionStart;
  const before = val.slice(0, cursorPos);
  const wordMatch = before.match(/[a-zA-Z_]\w*$/);
  const word = wordMatch ? wordMatch[0] : "";
  const fieldKeys = getFormulaFieldKeys();
  const allItems = [...fieldKeys, ...formulaFunctions.map((f) => f.key)];
  const filtered = word
    ? allItems.filter((item) => item.toLowerCase().startsWith(word.toLowerCase()))
    : allItems;
  if (!filtered.length) {
    formulaAutocomplete.value.show = false;
    return;
  }
  const rect = ta.getBoundingClientRect();
  formulaAutocomplete.value = { show: true, items: filtered, x: rect.left, y: rect.bottom };
}
function insertFormulaCompletion(item: string, nodeData: any) {
  const isFunc = formulaFunctions.some((f) => f.key === item);
  const suffix = isFunc ? "()" : "";
  const ta = document.querySelector(".ge-formula-textarea") as HTMLTextAreaElement;
  if (ta) {
    const cursor = ta.selectionStart;
    const val = ta.value;
    const before = val.slice(0, cursor);
    const wordMatch = before.match(/[a-zA-Z_]\w*$/);
    const wordStart = wordMatch ? cursor - wordMatch[0].length : cursor;
    nodeData.expr = val.slice(0, wordStart) + item + suffix + val.slice(cursor);
    nextTick(() => {
      const newPos = wordStart + item.length + (isFunc ? 1 : 0);
      ta.selectionStart = ta.selectionEnd = newPos;
      ta.focus();
    });
  }
  formulaAutocomplete.value.show = false;
}

let _seq = 0;
function uid(p = "n"): string {
  _seq += 1;
  return `${p}_${Date.now().toString(36)}_${_seq}`;
}
function nodeById(id?: string): GNode | undefined {
  if (!id) return undefined;
  return graph.nodes.find((n) => n.id === id);
}

// 节点库：仅 4 类（输出 / 数值源 / 条件 / 赋值）
const palette = [
  { group: "结果", items: [{ type: "output" as GNodeType, title: "输出" }] },
  { group: "数值", items: [{ type: "value" as GNodeType, title: "数值源" }] },
  {
    group: "逻辑",
    items: [
      { type: "if" as GNodeType, title: "条件(IF)" },
      { type: "assign" as GNodeType, title: "赋值" },
    ],
  },
];

const IND_VALUE_KINDS = ["FIELD", "CONST", "FORMULA", "OP", "VAR", "CONSUMER_DEMAND"];
const IND_VALUE_KIND_LABEL: Record<string, string> = {
  FIELD: "产业字段现值",
  CONST: "常量",
  FORMULA: "公式(mathjs)",
  OP: "运算(列表/字典/算术/比较)",
  VAR: "运行期变量",
  CONSUMER_DEMAND: "消费者需求总数(按所在地)",
};
const IND_ARITH_OPS = ARITH_OPS;
const IND_BOOL_OPS = ["CMP_EQ", "CMP_NE", "CMP_GT", "CMP_LT", "CMP_GTE", "CMP_LTE"];
const IND_LIST_OPS = Object.keys(OP_ARG_SPECS).filter(
  (k) => !k.startsWith("DICT_") && !ARITH_OPS.includes(k) && !k.startsWith("CMP_"),
);
const IND_DICT_OPS = Object.keys(OP_ARG_SPECS).filter((k) => k.startsWith("DICT_"));

const selectedNode = computed(
  () => graph.nodes.find((n) => n.id === selectedId.value) || null,
);

// 可选字段（本产业类型的其它字段）
const fieldOptions = computed<{ value: string; label: string }[]>(() => {
  const out: { value: string; label: string }[] = [];
  for (const f of props.availableFields || []) {
    const key = f.fieldKey;
    if (!key) continue;
    out.push({ value: key, label: f.name || f.fieldKey || key });
  }
  return out;
});
const formulaVars = computed(() =>
  (props.availableFields || [])
    .map((f) => f.fieldKey)
    .filter(Boolean)
    .join(", "),
);

const opArgs = computed(() =>
  selectedNode.value && selectedNode.value.data.kind === "OP"
    ? OP_ARG_SPECS[selectedNode.value.data.op as string] || []
    : [],
);

// ===== 校验提示 =====
const outputNode = computed(() => graph.nodes.find((n) => n.type === "output"));
const warnings = computed<string[]>(() => {
  const w: string[] = [];
  if (!outputNode.value) w.push("缺少「输出」节点（计算结果汇点）");
  else {
    const connected = graph.edges.some(
      (e) => e.target === outputNode.value!.id && e.targetHandle === "value",
    );
    if (!connected) w.push("「输出」节点的「值」端口未连接任何表达式");
  }
  return w;
});

// ===== 坐标计算 =====
function portRelY(idx: number): number {
  return HEADER_H + PORT_TOP + idx * PORT_GAP;
}
function portStyle(kind: "in" | "out", idx: number) {
  const cy = portRelY(idx);
  const left = kind === "in" ? PORT_INSET - DOT / 2 : NODE_W - PORT_INSET - DOT / 2;
  return { top: cy - DOT / 2 + "px", left: left + "px" };
}
function portAbs(node: GNode, kind: "in" | "out", handle: string) {
  const list = kind === "in" ? indInputHandles(node) : indOutputHandles(node);
  const idx = list.indexOf(handle);
  if (idx < 0) return null;
  const cy = portRelY(idx);
  const cx = kind === "in" ? PORT_INSET : NODE_W - PORT_INSET;
  return { x: node.x + cx, y: node.y + cy };
}
function infoStyle(kind: "in" | "out", idx: number) {
  const cy = portRelY(idx);
  const top = cy - 7 + "px";
  if (kind === "in") return { left: "22px", width: COL_W + "px", top };
  return { right: "22px", width: COL_W + "px", top };
}
function portTitle(node: GNode, kind: "in" | "out", idx: number): string {
  const label = indPortLabel(node, kind, idx);
  const type = indPortType(node, kind, idx);
  return type ? `${label}（${type}）` : label;
}
function nodeStyle(node: GNode) {
  const inN = indInputHandles(node).length;
  const outN = indOutputHandles(node).length;
  const portN = Math.max(inN, outN, 1);
  const h = HEADER_H + PORT_TOP + (portN - 1) * PORT_GAP + DOT + 14;
  return {
    left: node.x + "px",
    top: node.y + "px",
    width: NODE_W + "px",
    minHeight: h + "px",
    borderColor: NODE_META[node.type].color,
  };
}
const svgW = computed(() => {
  const maxX = graph.nodes.reduce((m, n) => Math.max(m, n.x + NODE_W), 0);
  return Math.max(900, maxX + 200);
});
const svgH = computed(() => {
  const maxY = graph.nodes.reduce((m, n) => {
    const portN = Math.max(indInputHandles(n).length, indOutputHandles(n).length, 1);
    const h = HEADER_H + PORT_TOP + (portN - 1) * PORT_GAP + DOT + 70;
    return Math.max(m, n.y + h);
  }, 0);
  return Math.max(600, maxY + 200);
});
function edgePath(edge: any): string | null {
  const s = nodeById(edge.source);
  const t = nodeById(edge.target);
  if (!s || !t) return null;
  const a = portAbs(s, "out", edge.sourceHandle);
  const b = portAbs(t, "in", edge.targetHandle);
  if (!a || !b) return null;
  const dx = Math.max(40, Math.abs(b.x - a.x) / 2);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}

// ===== 节点摘要 =====
function fieldLabel(key?: string): string {
  if (!key) return "未选字段";
  return fieldOptions.value.find((x) => x.value === key)?.label || key;
}
function nodeSummary(n: GNode): string {
  const d = n.data || {};
  switch (n.type) {
    case "output":
      return "结果输出";
    case "value":
      if (d.kind === "FIELD") return `字段·${fieldLabel(d.fieldKey)}`;
      if (d.kind === "CONST") return `常量·${d.value ?? ""}`;
      if (d.kind === "FORMULA") return `公式·${d.expr ?? ""}`;
      if (d.kind === "OP") return OP_LABELS_FULL[d.op as string] || d.op || "";
      if (d.kind === "VAR") return `变量·${d.name || ""}`;
      if (d.kind === "CONSUMER_DEMAND") return "消费者需求总数";
      return d.kind || "";
    case "if":
      return "条件分支(值返回)";
    case "assign":
      return `赋值→${d.name || ""}`;
    default:
      return "";
  }
}

// ===== 操作 =====
function select(id: string) {
  selectedId.value = id;
}
function addNode(type: GNodeType) {
  if (type === "output" && outputNode.value) {
    ElMessage.warning("「输出」节点已存在，计算图只能有一个结果汇点");
    select(outputNode.value.id);
    return;
  }
  const n: GNode = {
    id: uid(type),
    type,
    x: 300 + (graph.nodes.length % 6) * 28,
    y: 60 + (graph.nodes.length % 12) * 22,
    data: defaultData(type),
  };
  graph.nodes.push(n);
  select(n.id);
}
function defaultData(type: GNodeType): Record<string, any> {
  switch (type) {
    case "output":
      return {};
    case "value":
      return { kind: "CONST", value: "0" };
    case "if":
      return {};
    case "assign":
      return { name: "" };
    default:
      return {};
  }
}
function removeNode(id: string) {
  const i = graph.nodes.findIndex((n) => n.id === id);
  if (i >= 0) graph.nodes.splice(i, 1);
  graph.edges = graph.edges.filter((e) => e.source !== id && e.target !== id);
  if (selectedId.value === id) selectedId.value = null;
}
function removeEdge(id: string) {
  graph.edges = graph.edges.filter((e) => e.id !== id);
}
function onPortClick(nodeId: string, handle: string, kind: "in" | "out") {
  if (kind === "out") {
    pending.value =
      pending.value && pending.value.nodeId === nodeId && pending.value.handle === handle
        ? null
        : { nodeId, handle };
    return;
  }
  if (!pending.value) return;
  if (pending.value.nodeId === nodeId) {
    pending.value = null;
    return;
  }
  const idx = graph.edges.findIndex((e) => e.target === nodeId && e.targetHandle === handle);
  if (idx >= 0) graph.edges.splice(idx, 1);
  graph.edges.push({
    id: uid("e"),
    source: pending.value.nodeId,
    sourceHandle: pending.value.handle,
    target: nodeId,
    targetHandle: handle,
  });
  pending.value = null;
}

// ===== 拖拽 =====
const drag = ref<{ id: string; sx: number; sy: number; ox: number; oy: number } | null>(null);
function startDrag(node: GNode, e: MouseEvent) {
  select(node.id);
  drag.value = { id: node.id, sx: e.clientX, sy: e.clientY, ox: node.x, oy: node.y };
  window.addEventListener("mousemove", onDragMove);
  window.addEventListener("mouseup", onDragUp);
}
function onDragMove(e: MouseEvent) {
  if (!drag.value) return;
  const n = nodeById(drag.value.id);
  if (!n) return;
  // 屏幕位移需除以 zoom 才能换算回世界坐标（画布可能被缩放）。
  n.x = Math.max(0, drag.value.ox + (e.clientX - drag.value.sx) / zoom.value);
  n.y = Math.max(0, drag.value.oy + (e.clientY - drag.value.sy) / zoom.value);
}
function onDragUp() {
  drag.value = null;
  window.removeEventListener("mousemove", onDragMove);
  window.removeEventListener("mouseup", onDragUp);
}
function onCanvasDown(e: MouseEvent) {
  // 点在节点内部时不平移（节点标题拖拽用 @mousedown.stop 已拦截，节点体点击保持选中查看属性）。
  if ((e.target as HTMLElement).closest(".ge-node")) return;
  // 空白处：取消选中 + 拖拽平移整个视图。
  selectedId.value = null;
  pending.value = null;
  startPan(e);
}

// ===== 属性面板辅助 =====
function onKindChange() {
  const n = selectedNode.value;
  if (!n || n.type !== "value") return;
  const k = n.data.kind;
  if (k === "OP" && !n.data.op) n.data.op = "ADD";
  n.data.argLiterals = k === "OP" ? n.data.argLiterals || {} : {};
  if (k !== "FIELD") n.data.fieldKey = undefined;
  if (k !== "CONST") n.data.value = undefined;
  if (k !== "FORMULA") n.data.expr = undefined;
  if (k !== "OP") n.data.op = undefined;
  if (k !== "VAR") n.data.name = undefined;
}
function onOpChange() {
  if (selectedNode.value) selectedNode.value.data.argLiterals = {};
}
function setConstEmpty(kind: "dict" | "list") {
  if (!selectedNode.value) return;
  selectedNode.value.data.value = kind === "dict" ? "{}" : "[]";
}

function toggleSource() {
  showSource.value = !showSource.value;
}
function onClear() {
  graph.nodes = [];
  graph.edges = [];
  selectedId.value = null;
  pending.value = null;
}

const sourceJson = computed(() =>
  JSON.stringify({ nodes: graph.nodes, edges: graph.edges }, null, 2),
);

// ===== 加载 / 序列化（v-model） =====
function loadFrom(str?: string | null) {
  if (!str) {
    graph.nodes = [];
    graph.edges = [];
  } else {
    try {
      const g = JSON.parse(str);
      graph.nodes = Array.isArray(g.nodes) ? g.nodes : [];
      graph.edges = Array.isArray(g.edges) ? g.edges : [];
    } catch {
      graph.nodes = [];
      graph.edges = [];
    }
  }
  selectedId.value = null;
  pending.value = null;
}
loadFrom(props.modelValue);

let emitTimer: any = null;
function scheduleEmit() {
  if (emitTimer) clearTimeout(emitTimer);
  emitTimer = setTimeout(() => {
    emit("update:modelValue", JSON.stringify({ nodes: graph.nodes, edges: graph.edges }));
  }, 150);
}
watch(() => graph, scheduleEmit, { deep: true });
// 外部 modelValue 变化时（如切换字段）重新加载，但避免与自身 emit 回环。
watch(
  () => props.modelValue,
  (v) => {
    const cur = JSON.stringify({ nodes: graph.nodes, edges: graph.edges });
    if (v !== cur) loadFrom(v);
  },
);

onMounted(() => {
  /* 无需远程数据：字段由父组件以 availableFields 传入 */
  window.addEventListener("keydown", onGlobalKeydown);
});
onUnmounted(() => {
  window.removeEventListener("keydown", onGlobalKeydown);
});
</script>

<style scoped>
.ge {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #f5f6fa;
}
.ge-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  flex-wrap: wrap;
}
.ge-hint {
  color: #909399;
  font-size: 12px;
  margin-left: auto;
}
.ge-connecting {
  color: #e67e22;
  font-size: 12px;
  margin-left: auto;
  font-weight: bold;
}
.ge-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.ge-palette {
  flex: 0 0 auto;
  width: clamp(150px, 11vw, 210px);
  padding: 10px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  overflow: auto;
}
.ge-palette-title {
  font-weight: bold;
  margin-bottom: 8px;
  color: #303133;
}
.ge-palette-group {
  margin-bottom: 12px;
}
.ge-palette-group-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.ge-palette-item {
  border: 1px solid #e4e7ed;
  border-left: 5px solid #ccc;
  border-radius: 5px;
  padding: 5px 8px;
  margin-bottom: 6px;
  font-size: 13px;
  background: #fafafa;
  cursor: pointer;
  user-select: none;
}
.ge-palette-item:hover {
  background: #ecf5ff;
}
.ge-canvas {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  position: relative;
  overflow: hidden;
  background: #eef0f4;
  background-image: radial-gradient(#d5d8de 1px, transparent 1px);
  background-size: 22px 22px;
  user-select: none;
  cursor: grab;
}
.ge-canvas:active {
  cursor: grabbing;
}
/* 视口层：所有节点 / 连线都在其内部，缩放与平移只改它的 transform；
   尺寸由内部绝对定位元素决定，本身无需显式宽高（变换原点由 composable 设为 0 0）。 */
.ge-viewport {
  position: absolute;
  top: 0;
  left: 0;
}
.ge-zoom {
  margin-left: 6px;
}
.ge-svg {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
}
.ge-edge {
  fill: none;
  stroke: #7f8c8d;
  stroke-width: 2;
  pointer-events: stroke;
  cursor: pointer;
}
.ge-edge:hover {
  stroke: #e74c3c;
  stroke-width: 3;
}
.ge-node {
  position: absolute;
  box-sizing: border-box;
  background: #fff;
  border: 2px solid #ccc;
  border-radius: 8px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
  font-size: 12px;
  cursor: default;
  z-index: 1;
}
.ge-node-sel {
  outline: 2px solid #409eff;
  z-index: 10;
}
.ge-node-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  border-radius: 6px 6px 0 0;
  color: #fff;
  font-weight: bold;
  cursor: grab;
  user-select: none;
}
.ge-node-del {
  cursor: pointer;
  font-size: 12px;
}
.ge-node-cap {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 4px;
  font-size: 11px;
  line-height: 1.35;
  color: #909399;
  word-break: break-all;
}
.ge-port {
  position: absolute;
  box-sizing: border-box;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  border: 2px solid #34495e;
  cursor: crosshair;
  z-index: 2;
}
.ge-port-info {
  position: absolute;
  display: flex;
  flex-direction: column;
  gap: 1px;
  pointer-events: none;
  z-index: 3;
}
.ge-port-info-out {
  text-align: right;
  align-items: flex-end;
}
.ge-port-name {
  font-size: 11px;
  font-weight: 600;
  line-height: 14px;
  color: #34495e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ge-port-row {
  display: flex;
  gap: 4px;
  align-items: center;
}
.ge-port-info-out .ge-port-row {
  justify-content: flex-end;
}
.ge-port-type {
  flex: 0 0 auto;
  font-size: 10px;
  line-height: 13px;
  color: #409eff;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  border-radius: 3px;
  padding: 0 4px;
  white-space: nowrap;
}
.ge-port-info-out .ge-port-name {
  color: #c0392b;
}
.ge-port-hot {
  border-color: #e67e22;
  background: #fef0e6;
}
.ge-port:hover {
  background: #409eff;
  border-color: #409eff;
}
.ge-panel {
  flex: 0 0 auto;
  width: clamp(300px, 21vw, 400px);
  padding: 12px;
  background: #fff;
  border-left: 1px solid #e4e7ed;
  overflow: auto;
}
.ge-sel-title {
  font-weight: bold;
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: #303133;
}
.ge-sel-empty {
  color: #909399;
  font-size: 12px;
}
.ge-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  background: #f4f4f5;
  padding: 6px 8px;
  border-radius: 5px;
  margin-top: 4px;
}
.ge-warn {
  margin-bottom: 8px;
}
.ge-source-title {
  font-weight: bold;
  margin-bottom: 6px;
  color: #303133;
}
.json-box {
  background: #2d2d2d;
  color: #f8f8f2;
  padding: 10px;
  border-radius: 6px;
  font-size: 11px;
  max-height: 100%;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

/* ===== 搜索 ===== */
.ge-search-bar {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ge-search-input {
  width: 180px;
}
.ge-search-count {
  font-size: 11px;
  color: #909399;
  white-space: nowrap;
}

/* ===== 搜索高亮 / 暗化 ===== */
.ge-node-match {
  outline: 2px solid #e6a23c !important;
  box-shadow: 0 0 8px rgba(230, 162, 60, 0.5);
}
.ge-node-dim {
  opacity: 0.3;
}

/* ===== 折叠按钮 ===== */
.ge-fold-btn {
  cursor: pointer;
  font-size: 10px;
  margin-right: 3px;
  display: inline-block;
  width: 14px;
  text-align: center;
}
.ge-fold-btn:hover {
  color: #ecf5ff;
}
.ge-collapse-badge {
  font-size: 10px;
  color: #e67e22;
  background: #fef0e6;
  padding: 2px 8px;
  text-align: center;
  border-top: 1px dashed #f5dab1;
}

/* ===== FORMULA 编辑器增强 ===== */
.ge-formula-editor {
  width: 100%;
  position: relative;
}
.ge-formula-textarea {
  width: 100%;
  min-height: 80px;
  padding: 8px 10px;
  font-family: "Cascadia Code", "Fira Code", "Consolas", "Courier New", monospace;
  font-size: 13px;
  line-height: 1.5;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fafbfc;
  color: #303133;
  resize: vertical;
  outline: none;
  tab-size: 2;
  box-sizing: border-box;
}
.ge-formula-textarea:focus {
  border-color: #409eff;
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.2);
}
.ge-formula-textarea.ge-formula-error {
  border-color: #f56c6c;
  background: #fef0f0;
}
.ge-formula-error-msg {
  font-size: 11px;
  color: #f56c6c;
  margin-top: 4px;
  line-height: 1.3;
}
.ge-formula-hints {
  margin-top: 6px;
  font-size: 11px;
  color: #909399;
  line-height: 1.6;
}
.ge-formula-hint-title {
  margin-bottom: 2px;
}
.ge-formula-key {
  display: inline-block;
  background: #ecf5ff;
  color: #409eff;
  border: 1px solid #d9ecff;
  border-radius: 3px;
  padding: 0 4px;
  margin: 0 2px;
  font-size: 10px;
  font-family: monospace;
}
.ge-formula-fn {
  display: inline-block;
  background: #f0f9eb;
  color: #67c23a;
  border: 1px solid #e1f3d8;
  border-radius: 3px;
  padding: 0 4px;
  margin: 0 2px;
  font-size: 10px;
  font-family: monospace;
}

/* ===== 自动补全下拉 ===== */
.ge-formula-autocomplete {
  position: fixed;
  z-index: 9999;
  background: #fff;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  max-height: 200px;
  overflow-y: auto;
  min-width: 160px;
}
.ge-formula-ac-item {
  padding: 4px 10px;
  font-size: 12px;
  font-family: monospace;
  cursor: pointer;
  color: #303133;
}
.ge-formula-ac-item:hover {
  background: #ecf5ff;
  color: #409eff;
}
</style>
