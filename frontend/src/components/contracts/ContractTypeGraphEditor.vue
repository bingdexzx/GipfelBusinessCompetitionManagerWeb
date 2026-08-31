<template>
  <div class="ge">
    <!-- 顶部工具栏 -->
    <div class="ge-toolbar">
      <el-button @click="$emit('close')">返回</el-button>
      <template v-if="!meta.id">
        <el-input v-model="meta.key" disabled placeholder="自动生成（名称拼音）" style="width: 150px" />
        <el-input v-model="meta.name" placeholder="名称" style="width: 140px" />
      </template>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
      <el-button @click="toggleSource">{{ showSource ? "画布视图" : "源码 JSON" }}</el-button>
      <el-button @click="applyAutoLayout" title="自动分层排列节点">自动布局</el-button>
      <el-button @click="openTrial" :disabled="!meta.id" title="试算面板">试算</el-button>
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
      <span v-else class="ge-hint">拖动节点标题移动；点输出端口→点输入端口连线；点连线可删除</span>
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
            :class="{ 'ge-edge-bad': edgeBad(e) }"
            @click.stop="removeEdge(e.id)"
          >
            <title>{{ edgeTip(e) }}</title>
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
                v-if="n.type === 'if' || n.type === 'foreach'"
                class="ge-fold-btn"
                @click.stop="toggleCollapse(n.id)"
              >{{ isCollapsed(n.id) ? '▶' : '▼' }}</span>
              {{ NODE_META[n.type].title }}
            </span>
            <span v-if="n.type !== 'root'" class="ge-node-del" @click.stop="removeNode(n.id)"
              >✕</span
            >
          </div>
          <div v-if="isCollapsed(n.id)" class="ge-collapse-badge">
            {{ hiddenChildCount(n.id) }} 个节点已隐藏
          </div>
          <div class="ge-node-cap">{{ nodeSummary(n) }}</div>

          <!-- 输入端口 + 名称 + 用途说明 -->
          <template v-for="(h, i) in inputHandles(n)" :key="'i' + h">
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
                <span class="ge-port-name">{{ portLabel(n, "in", i) }}</span>
                <span class="ge-port-type">{{ portType(n, "in", i) }}</span>
              </div>
            </div>
          </template>

          <!-- 输出端口 + 名称 + 用途说明（右栏，镜像） -->
          <template v-for="(h, j) in outputHandles(n)" :key="'o' + h">
            <div class="ge-port-info ge-port-info-out" :style="infoStyle('out', j)">
              <div class="ge-port-row">
                <span class="ge-port-name">{{ portLabel(n, "out", j) }}</span>
                <span class="ge-port-type">{{ portType(n, "out", j) }}</span>
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
        <template v-if="selectedNode">
          <div class="ge-sel-title">
            {{ NODE_META[selectedNode.type].title }}
            <el-button size="small" type="danger" plain @click="removeNode(selectedNode.id)"
              >删除</el-button
            >
          </div>
          <el-divider />

          <!-- 参与方 -->
          <template v-if="selectedNode.type === 'party'">
            <el-form label-width="80px" size="small">
              <el-form-item label="角色编码"
                ><el-input v-model="selectedNode.data.role"
              /></el-form-item>
              <el-form-item label="显示名"
                ><el-input v-model="selectedNode.data.label"
              /></el-form-item>
              <el-form-item label="主办方">
                <el-switch v-model="selectedNode.data.isHost" />
                <span class="ge-tip">主办方(主席团)不计产业字段；经济管理中心为普通参与方</span>
              </el-form-item>
              <el-form-item label="可选">
                <el-switch v-model="selectedNode.data.selectable" />
              </el-form-item>
              <el-form-item label="限定产业">
                <el-select
                  v-model="selectedNode.data.industryTypeId"
                  placeholder="不限"
                  clearable
                  filterable
                  style="width: 100%"
                >
                  <el-option
                    v-for="it in industryTypes"
                    :key="it.id"
                    :label="it.name"
                    :value="it.id"
                  />
                </el-select>
              </el-form-item>
            </el-form>
          </template>

          <!-- 输入项 -->
          <template v-else-if="selectedNode.type === 'input'">
            <el-form label-width="80px" size="small">
              <el-form-item label="字段键"
                ><el-input v-model="selectedNode.data.key"
              /></el-form-item>
              <el-form-item label="显示名"
                ><el-input v-model="selectedNode.data.label"
              /></el-form-item>
              <el-form-item label="类型">
                <el-select
                  v-model="selectedNode.data.type"
                  style="width: 100%"
                  @change="onInputTypeChange"
                >
                  <el-option label="数字" value="number" />
                  <el-option label="文本" value="string" />
                  <el-option label="布尔" value="boolean" />
                  <el-option label="实体" value="ENTITY" />
                  <el-option label="节点列表" value="nodeRoute" />
                  <el-option label="地图节点" value="mapNode" />
                  <el-option label="列表" value="list" />
                  <el-option label="字典" value="dict" />
                  <el-option label="原料清单" value="materialList" />
                  <el-option label="零件清单" value="partList" />
                  <el-option label="产品清单" value="productList" />
                  <el-option label="基建清单" value="infrastructureList" />
                  <el-option label="燃料清单" value="fuelList" />
                  <el-option label="载具清单" value="vehicleList" />
                  <el-option label="仓库清单" value="warehouseList" />
                  <el-option label="科技树清单" value="techNode" />
                </el-select>
              </el-form-item>
              <el-form-item label="关联实体">
                <el-select
                  v-model="selectedNode.data.entityType"
                  placeholder="无"
                  clearable
                  filterable
                  style="width: 100%"
                >
                  <el-option
                    v-for="t in ENTITY_TYPES"
                    :key="t"
                    :label="ENTITY_TYPE_LABEL[t] || t"
                    :value="t"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="必填"
                ><el-switch v-model="selectedNode.data.required"
              /></el-form-item>
              <el-form-item label="默认值">
                <template
                  v-if="selectedNode.data.type === 'dict' || selectedNode.data.type === 'list'"
                >
                  <el-input
                    type="textarea"
                    :rows="3"
                    :model-value="defaultJsonText"
                    :placeholder="selectedNode.data.type === 'dict' ? '{}' : '[]'"
                    @change="onDefaultJsonChange"
                  />
                </template>
                <el-input v-else v-model="selectedNode.data.default" />
              </el-form-item>
              <el-form-item label="控制流上级">
                <span v-if="selectedInputBranch" class="ge-branch-on"
                  >已挂到 IF 的「{{ selectedInputBranch.port }}」之下（创建表单按条件显隐）</span
                >
                <span v-else class="ge-tip-inline">未挂（始终显示）</span>
              </el-form-item>
            </el-form>
            <div v-if="selectedNode.type === 'input'" class="ge-tip">
              本输入项左侧有「上级」控制流端口：把某个
              <b>IF 条件节点</b>的「真分支 / 假分支」输出端口连到此处，该输入项即只在创建合同时
              当条件成立 / 不成立才显示并要求填写（条件可依赖参与方产业类型或其他已填输入项）。拖 IF
              的「真分支 / 假分支」端口 → 点本节点的「上级」端口即可连线。
            </div>
            <!-- 输入项类型说明：放在表单下方（右侧），不挤在节点编辑区内 -->
            <div class="ge-node-desc">
              <div
                v-if="selectedNode.data.type === 'dict' || selectedNode.data.type === 'list'"
                class="ge-tip"
              >
                字典请输入合法 JSON 对象（空字典填 <code>{}</code>），列表请输入合法 JSON
                数组（空列表填 <code>[]</code>）。
              </div>
              <div v-else-if="selectedNode.data.type === 'materialList'" class="ge-tip">
                原料清单输入源：创建合同时由用户在「合同数据」处多选原料并填写各自数量，保存为
                <code>{"原料名称": 数量}</code>
                字典（键为原料名字符串、值为整数数量）。选择该类型已自动关联实体=原料(MATERIAL)。
                <br />
                本输入源有四个输出端点：<b>输出</b>（原始字典，可接入公式作用域）、
                <b>碳排放合计</b>（按比赛查每种原料「碳排放系数 × 数量」之和）、
                <b>原料总价格</b>（按比赛查每种原料「价格 × 数量」之和）与
                <b>原料总数量</b>（直接把清单中各原料数量相加，连线到下游数值端口即可参与效果/检查计算，无需查表），均连线到下游数值端口即可参与效果/检查计算。
                左侧还有一个<b>参与方</b>输入端口：把参与方连到此处后，「原料总价格」会按该参与方产业类型的<b>所在地</b>节点价格计算（地点价优先，无则回退基础价）。
              </div>
              <div v-else-if="selectedNode.data.type === 'partList'" class="ge-tip">
                零件清单输入源：创建合同时由用户在「合同数据」处多选零件并填写各自数量，保存为
                <code>{"零件名称": 数量}</code>
                字典（键为零件名字符串、值为整数数量）。选择该类型已自动关联实体=零件(PART)。
                <br />
                本输入源有四个输出端点：<b>输出</b>（原始字典，可接入公式作用域）、
                <b>所需原料</b>（按比赛查询每个零件的配比，将「数量 × 系数」按原料累加，输出
                <code>{"原料名称": 总数量}</code> 字典，连线到下游字典/公式端口即可直接拿到该批零件所需的全部原料及数量，无需手动拆解）、
                <b>所需的科技节点</b>（按比赛查询清单中每个零件的「科技需求(TechNode)」，收集这些科技节点名称，去重后输出字符串数组，连线到下游列表/字典端口即可直接拿到该批零件所需的全部科技节点，无需手动查表）<b>与</b>
                <b>零件总件数</b>（直接把清单中各零件数量相加，连线到下游数值端口即可参与效果/检查计算，无需查表）。
              </div>
              <div v-else-if="selectedNode.data.type === 'productList'" class="ge-tip">
                产品清单输入源：创建合同时由用户在「合同数据」处多选产品并填写各自数量，保存为
                <code>{"产品名称": 数量}</code>
                字典（键为产品名字符串、值为整数数量）。选择该类型已自动关联实体=产品(PRODUCT)。
                <br />
                本输入源有四个输出端点：<b>输出</b>（原始字典，可接入公式作用域）、
                <b>需要的零件</b>（按比赛查询每个产品的配比，将「数量 × 系数」按零件累加，输出
                <code>{"零件名称": 总数量}</code> 字典，连线到下游字典/公式端口即可直接拿到该批产品所需的全部零件及数量，无需手动拆解）、
                <b>所需的科技节点</b>（按比赛查询清单中每个产品的「科技需求(TechNode)」，收集这些科技节点名称，去重后输出字符串数组，连线到下游列表/字典端口即可直接拿到该批产品所需的全部科技节点，无需手动查表）<b>与</b>
                <b>产品总件数</b>（直接把清单中各产品数量相加，连线到下游数值端口即可参与效果/检查计算，无需查表）。
              </div>
              <div v-else-if="selectedNode.data.type === 'infrastructureList'" class="ge-tip">
                基建清单输入源：创建合同时由用户在「合同数据」处多选基建并填写各自数量，保存为
                <code>{"基建名称": 数量}</code>
                字典（键为基建名字符串、值为整数数量）。选择该类型已自动关联实体=基建(INFRASTRUCTURE)。
                <br />
                本输入源有 10 个输出端点：<b>输出</b>（原始字典
                <code>{"基建名称": 数量}</code>，可接入字典/公式端口）、以及 9 个聚合浮点端点——
                <b>基建总价格</b>、<b>基建总占地面积</b>、<b>基建总就业率加成</b>、<b>基建总人口加成</b>、
                <b>基建总高素质人口加成</b>、<b>基建总幸福度加成</b>、<b>基建总人均收益加成</b>、
                <b>基建总减碳排放加成</b>、<b>基建启用总费用</b>。每个聚合端点按比赛查询对应字段，将「字段值 × 输入数量」求和，                连线到下游数值端口即可参与效果/检查计算，无需手动逐项乘加。
                <br />
                左侧还有一个<b>基建列表</b>输入端口：连上一个基建名称的数组（如 CONST 数值源填
                <code>["基建A","基建B"]</code>，或列表类型输入项的默认值）后，创建合同时该清单的基建下拉
                <b>仅展示列表中的基建</b>；未连接则展示全部基建。
              </div>
              <div v-else-if="selectedNode.data.type === 'fuelList'" class="ge-tip">
                燃料清单输入源：创建合同时由用户在「合同数据」处多选燃料并填写各自数量，保存为
                <code>{"燃料名称": 数量}</code>
                字典（键为燃料名字符串、值为整数数量）。选择该类型已自动关联实体=燃料(FUEL)。
                <br />
                本输入源有三个输出端点：<b>输出</b>（原始字典
                <code>{"燃料名称": 数量}</code
                >，即燃料数量字典，可接入公式/字典端口）、
                <b>燃料总数量</b>（直接把清单中各燃料数量相加，连线到下游数值端口即可参与效果/检查计算，无需查表）<b>与</b>
                <b>燃料总价格</b>（按比赛查每种燃料的「每升价格 × 数量」求和，连线到下游数值端口即可参与效果/检查计算，无需手动逐项乘加）。
              </div>
              <div v-else-if="selectedNode.data.type === 'nodeRoute'" class="ge-tip">
                节点列表输入源：创建合同时由用户在「合同数据」处按顺序逐个添加地图节点（至少 2 个），保存为
                节点 id 的有序数组。选择该类型已自动关联为地图节点序列。
                <br />
                本输入源有三个输出端点：<b>输出</b>（原始节点 id 数组，可接入列表/公式）、
                <b>路程</b>（按比赛查询地图相邻节点最短路径距离之和，连线到下游数值端口即可参与效果/检查计算，无需再绕到数据源节点的「节点列表」端口）<b>与</b>
                <b>存在的路径类型</b>（按比赛查询与任一路点相连的边，取这些边所用路径类型的名称组成列表，可接入下游列表/字典端口）。
              </div>
              <div v-else-if="selectedNode.data.type === 'vehicleList'" class="ge-tip">
                载具清单输入源：创建合同时由用户在「合同数据」处多选载具并填写各自数量，保存为
                <code>{"载具名称": 数量}</code>
                字典（键为载具名字符串、值为整数数量）。选择该类型已自动关联实体=载具(VEHICLE)。
                <br />
                本输入源有 5 个输出端点：<b>输出</b>（原始字典
                <code>{"载具名称": 数量}</code
                >，即载具数量清单，可接入公式/字典端口）与
                4 个聚合浮点端点——<b>载具总价格</b>（按比赛查「价格 × 数量」之和）、
                <b>载具总载货量</b>（按比赛查「载货量(maxCargo) × 数量」之和）、
                <b>总每公里油耗</b>（按比赛查「每公里油耗(fuelConsumptionPerKm) × 数量」之和）、
                <b>总碳排数</b>（按比赛查「碳排放系数(carbonEmission) × 数量」之和，不乘每公里油耗）。
                每个聚合端点连线到下游数值端口即可参与效果/检查计算，无需手动逐项乘加。
                <br />
                左侧还有一个<b>载具列表</b>输入端口：连上一个载具名称的数组（如 CONST 数值源填
                <code>["车A","车B"]</code>，或列表类型输入项的默认值）后，创建合同时该清单的载具下拉
                <b>仅展示列表中的载具</b>；未连接则展示全部载具。
              </div>
              <div v-else-if="selectedNode.data.type === 'warehouseList'" class="ge-tip">
                仓库清单输入源：创建合同时由用户在「合同数据」处多选仓库并填写各自数量，保存为
                <code>{"仓库名称": 数量}</code>
                字典（键为仓库名字符串、值为整数数量）。选择该类型已自动关联实体=仓库(WAREHOUSE)。
                <br />
                本输入源有三个输出端点：<b>输出</b>（原始字典
                <code>{"仓库名称": 数量}</code
                >，即仓库数量字典，可接入公式/字典端口）、
                <b>每种种类的仓库总存储量</b>（按比赛查每个仓库的「种类(type) + 容量(capacity)」，将清单中「容量 × 数量」按种类累加，输出
                <code>{"仓库种类(type)": 总存储量}</code>
                字典，如
                <code>{"MATERIAL": 1200, "PRODUCT": 800}</code>
                ，连线到下游字典/公式端口即可直接拿到各类仓库的总存储）<b>与</b>
                <b>仓库总价格</b>（按比赛查每种仓库「价格 × 数量」之和，连线到下游数值端口即可参与效果/检查计算，无需手动逐项乘加）。
              </div>
              <div v-else-if="selectedNode.data.type === 'techNode'" class="ge-tip">
                科技树清单输入源：创建合同时由用户在「合同数据」处<b>单选</b>一个科技树节点（无需填数量），保存为科技节点名称字符串。选择该类型已自动关联实体=科技节点(TECH_NODE)。
                <br />
                本输入源有三个输出端点：<b>输出</b>（选中的科技节点名，单值文本，可接入公式/条件）、
                <b>前置节点</b>（按比赛查询该科技节点的全部前置依赖节点名称，输出字符串数组，可接入下游列表/字典端口）<b>与</b>
                <b>研发费用</b>（按比赛查询该科技节点的 researchCost，作为单个浮点数输出，连线到下游数值端口即可参与效果/检查计算，无需手动查表）。
              </div>
              <!-- 输出端口说明：放在右侧（与节点类型说明同区），画布节点上不再显示长描述，避免撑出节点框 -->
              <div v-if="outputHandles(selectedNode).length" class="ge-port-desc-list">
                <div class="ge-port-desc-title">输出端口说明</div>
                <div
                  v-for="(h, idx) in outputHandles(selectedNode)"
                  :key="h"
                  class="ge-tip ge-port-desc-item"
                >
                  <b>{{ portLabel(selectedNode, "out", idx) }}</b>
                  <span class="ge-port-desc-type">{{ portType(selectedNode, "out", idx) }}</span>
                  <div>{{ portDesc(selectedNode, "out", idx) }}</div>
                </div>
              </div>
            </div>
          </template>

          <!-- 数值源 -->
          <template v-else-if="selectedNode.type === 'value'">
            <el-form label-width="80px" size="small">
              <el-form-item label="来源">
                <el-select
                  v-model="selectedNode.data.valueType"
                  style="width: 100%"
                  @change="onValueTypeChange"
                >
                  <el-option
                    v-for="t in VALUE_TYPES"
                    :key="t"
                    :label="VALUE_TYPE_LABEL[t] || t"
                    :value="t"
                  />
                </el-select>
              </el-form-item>
              <template v-if="selectedNode.data.valueType === 'ENTITY'">
                <el-form-item label="实体">
                  <el-select
                    v-model="selectedNode.data.entityType"
                    style="width: 100%"
                    @change="onEntityTypeChange"
                  >
                    <el-option
                      v-for="t in ENTITY_TYPES"
                      :key="t"
                      :label="ENTITY_TYPE_LABEL[t] || t"
                      :value="t"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="属性">
                  <el-select
                    v-model="selectedNode.data.attribute"
                    placeholder="选择字段"
                    clearable
                    filterable
                    allow-create
                    default-first-option
                    style="width: 100%"
                  >
                    <el-option
                      v-for="a in entityFields"
                      :key="a.key"
                      :label="a.label"
                      :value="a.key"
                    />
                  </el-select>
                </el-form-item>
                <div class="ge-tip">
                  数据源：运行时从数据管理读取该实体的真实属性。把「实体引用」端口连到输入项节点，取其
                  key 作为实体 id。
                </div>
              </template>
              <template v-else-if="selectedNode.data.valueType === 'FIELD'">
                <el-form-item label="产业字段">
                  <el-select
                    v-model="selectedNode.data.fieldKey"
                    placeholder="选择/输入字段"
                    clearable
                    filterable
                    allow-create
                    default-first-option
                    style="width: 100%"
                    @change="onFieldKeyChange"
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
                  数据源：运行时读取<b>某参与方公司当前</b>的产业字段值。把「字段所属方」端口连到参与方节点。数字字段返回数字，列表/字典字段返回数组/对象（可接入运算节点）。
                </div>
              </template>
              <template v-else-if="selectedNode.data.valueType === 'INDUSTRY_IS'">
                <el-form-item label="产业类型">
                  <el-select
                    v-model="selectedNode.data.industryTypeId"
                    placeholder="选择产业类型"
                    clearable
                    filterable
                    style="width: 100%"
                  >
                    <el-option
                      v-for="it in industryTypes"
                      :key="it.id"
                      :label="it.name"
                      :value="it.id"
                    />
                  </el-select>
                </el-form-item>
                <div class="ge-tip">
                  输出一个<b>布尔值</b>：判断「字段所属方」端口连到的参与方公司所属产业类型是否为所选产业。把「字段所属方」端口连到参与方节点；输出「布尔」连到「条件(IF)」的「条件」端口，驱动真/假分支。主办方/未绑定公司/未设产业类型时返回 false。
                </div>
              </template>
              <template v-else-if="selectedNode.data.valueType === 'INPUT'">
                <div class="ge-tip">把「键」输入端口连到输入项节点，取其值。</div>
              </template>
              <template v-else-if="selectedNode.data.valueType === 'CONST'">
                <el-form-item label="常量值"
                  ><el-input v-model="selectedNode.data.value" placeholder="数字或 JSON"
                /></el-form-item>
                <div class="ge-tip">
                  快捷填入：
                  <el-button size="small" link type="primary" @click="setConstEmpty('dict')"
                    >空字典 {}</el-button
                  >
                  <el-button size="small" link type="primary" @click="setConstEmpty('list')"
                    >空数组 []</el-button
                  >
                  <span class="ge-sub">用于输出空字典 / 空数组（如作为初始容器或清空写入值）</span>
                </div>
              </template>
              <template v-else-if="selectedNode.data.valueType === 'FORMULA'">
            <el-form-item label="公式">
              <div class="ge-formula-editor">
                <textarea
                  class="ge-formula-textarea"
                  :class="{ 'ge-formula-error': formulaValidationError }"
                  :value="selectedNode.data.expr"
                  @input="onFormulaInput($event, selectedNode.data)"
                  @keydown="onFormulaKeydown($event, selectedNode.data)"
                  placeholder="mathjs 表达式，作用域=输入项&#10;Ctrl+Space 触发自动补全"
                  spellcheck="false"
                ></textarea>
                <div v-if="formulaValidationError" class="ge-formula-error-msg">
                  {{ formulaValidationError }}
                </div>
              </div>
            </el-form-item>
            <div class="ge-formula-hints">
              <div class="ge-formula-hint-title">可用字段：
                <code v-for="k in getFormulaFieldKeys()" :key="k" class="ge-formula-key">{{ k }}</code>
                <span v-if="!getFormulaFieldKeys().length" class="ge-tip-inline">暂无字段</span>
              </div>
              <div class="ge-formula-hint-title">函数：
                <code v-for="f in formulaFunctions" :key="f.key" class="ge-formula-fn" :title="f.desc">{{ f.label }}</code>
              </div>
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
              <template v-else-if="selectedNode.data.valueType === 'VAR'">
                <el-form-item label="变量名"
                  ><el-input v-model="selectedNode.data.varName"
                /></el-form-item>
              </template>
            </el-form>
          </template>

          <!-- 效果 -->
          <template v-else-if="selectedNode.type === 'effect'">
            <el-form label-width="80px" size="small">
              <el-form-item label="运算">
                <el-select v-model="selectedNode.data.op" style="width: 100%">
                  <el-option
                    v-for="o in FIELD_OPS"
                    :key="o"
                    :label="FIELD_OP_LABEL[o] || o"
                    :value="o"
                  />
                </el-select>
              </el-form-item>
              <el-form-item label="产业字段">
                <el-select
                  v-model="selectedNode.data.fieldKey"
                  placeholder="选择/输入字段"
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
              <el-form-item label="组合方式">
                <el-select
                  v-model="selectedNode.data.valueOp"
                  placeholder="仅接「值」时无需选"
                  clearable
                  style="width: 100%"
                >
                  <el-option
                    v-for="o in VALUE_OPS"
                    :key="o"
                    :label="VALUE_OP_LABEL[o] || o"
                    :value="o"
                  />
                </el-select>
              </el-form-item>
            </el-form>
            <div class="ge-tip">
              把「参与方」端口连到参与方节点；把「值」端口连到数值/输入/运算节点。需要两个自动数值时，再连「值2」端口并选「组合方式」，写入量
              = 值 &lt;组合方式&gt; 值2（只接「值」时退化为原行为）。
            </div>
          </template>

          <!-- 检查 -->
          <template v-else-if="selectedNode.type === 'condition'">
            <el-form label-width="80px" size="small">
              <el-form-item label="种类">
                <el-select v-model="selectedNode.data.condKind" style="width: 100%">
                  <el-option
                    v-for="k in COND_KINDS"
                    :key="k"
                    :label="COND_KIND_LABEL[k] || k"
                    :value="k"
                  />
                </el-select>
              </el-form-item>
              <template v-if="selectedNode.data.condKind === 'INDUSTRY_IS'">
                <el-form-item label="限定产业">
                  <el-select
                    v-model="selectedNode.data.industryTypeId"
                    placeholder="选择产业类型"
                    clearable
                    filterable
                    style="width: 100%"
                  >
                    <el-option
                      v-for="it in industryTypes"
                      :key="it.id"
                      :label="it.name"
                      :value="it.id"
                    />
                  </el-select>
                </el-form-item>
              </template>
              <template v-else-if="selectedNode.data.condKind === 'VALUE_COMPARE'">
                <el-form-item label="比较">
                  <el-select v-model="selectedNode.data.op" style="width: 100%">
                    <el-option
                      v-for="o in VALUE_COMPARE_OPS"
                      :key="o"
                      :label="COMPARE_OP_LABEL[o] || o"
                      :value="o"
                    />
                  </el-select>
                </el-form-item>
                <div class="ge-tip">
                  把「值1」「值2」两个端口分别连到数值/输入/运算节点（如两个公司的 FIELD
                  数值源），引擎比较两端现值。要比某方字段就接一个 FIELD
                  数值源即可，无需绑定固定字段。
                </div>
              </template>
              <template v-else-if="selectedNode.data.condKind === 'DICT_COMPARE'">
                <el-form-item label="比较">
                  <el-select v-model="selectedNode.data.op" style="width: 100%">
                    <el-option
                      v-for="o in DICT_COMPARE_OPS"
                      :key="o"
                      :label="COMPARE_OP_LABEL[o] || o"
                      :value="o"
                    />
                  </el-select>
                </el-form-item>
                <div class="ge-tip">
                  把「值1」「值2」两个端口分别连到<strong>字典</strong>源（如 CONST 字典 / 字典运算节点 /
                  清单聚合字典：原料→数量、零件→数量等）。<br />
                  <strong>比较前提</strong>：值一的每个键都必须存在于值二中（值一键 ⊆ 值二键），否则直接判不过；<br />
                  <strong>逐键比较</strong>：满足前提后，对共有键逐一执行「值1[k] 比较 值2[k]」，全部满足才算通过。
                </div>
              </template>
              <template v-else-if="selectedNode.data.condKind === 'LIST_COMPARE'">
                <el-form-item label="比较">
                  <el-select v-model="selectedNode.data.op" style="width: 100%">
                    <el-option
                      v-for="o in LIST_COMPARE_OPS"
                      :key="o"
                      :label="COMPARE_OP_LABEL[o] || o"
                      :value="o"
                    />
                  </el-select>
                </el-form-item>
                <div class="ge-tip">
                  把「值1」「值2」两个端口分别连到<strong>列表</strong>源（如 CONST 列表 / 列表运算节点 /
                  清单聚合列表：某原料全部供应商、某公司分部清单等）。<br />
                  <strong>比较的是「元素集合的包含关系」（非长度）</strong>：
                  <ul style="margin: 4px 0 0; padding-left: 18px">
                    <li><strong>元素相等</strong>：两列表长度相同且对应位置元素一致；</li>
                    <li><strong>被包含</strong>：值一的每个元素都在值二中存在（值一 ⊆ 值二）；</li>
                    <li><strong>大于</strong>：值一<strong>真包含</strong>值二（值一 ⊃ 值二，值二 ⊆ 值一 且二者集合不等）；</li>
                    <li><strong>大于等于</strong>：值一<strong>包含</strong>值二（值一 ⊇ 值二，值二 ⊆ 值一，含相等）；</li>
                    <li><strong>等于</strong>：两列表<strong>元素集合完全相同</strong>（值一 ⊆ 值二 且 值二 ⊆ 值一）。</li>
                  </ul>
                </div>
              </template>
              <template v-else>
                <el-form-item label="比较">
                  <el-select v-model="selectedNode.data.op" style="width: 100%">
                    <el-option
                      v-for="o in COMPARE_OPS"
                      :key="o"
                      :label="COMPARE_OP_LABEL[o] || o"
                      :value="o"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="产业字段">
                  <el-select
                    v-model="selectedNode.data.fieldKey"
                    placeholder="选择/输入字段"
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
                  兼容旧版：左操作数为「参与方」端口所指公司的产业字段，右操作数为「值」端口连入的数值节点。
                </div>
                <el-alert
                  v-if="fieldCompareLengthHint"
                  type="warning"
                  :closable="false"
                  show-icon
                  class="ge-warn"
                  :title="`注意：所选字段是${fieldCompareLengthHint.typeLabel}类型`"
                  description="这里的 ≥ / ≤ / > / < / = 比较的是「元素个数（长度）」，不是里面的数值。例如「合作伙伴列表 ≥ 3」表示列表里至少有 3 个元素。若想判断内容是否包含某元素，请用 CONTAINS / HAS_KEY（需在 JSON 中配置或由超管协助）。"
                />
              </template>
              <el-form-item label="错误信息">
                <el-input
                  v-model="selectedNode.data.errorMessage"
                  type="textarea"
                  :rows="2"
                  placeholder="检查不通过时展示给用户的提示（留空则用系统默认说明）"
                  style="width: 100%"
                />
              </el-form-item>
              <el-form-item label="控制流上级">
                <span v-if="selectedConditionBranch" class="ge-branch-on"
                  >已挂到 IF 的「{{ selectedConditionBranch.port }}」之下（仅该分支成立时才执行检查）</span
                >
                <span v-else class="ge-tip-inline">未挂（始终执行）</span>
              </el-form-item>
            </el-form>
            <div v-if="selectedNode.data.condKind === 'INDUSTRY_IS'" class="ge-tip">
              把「参与方」端口连到参与方节点。
            </div>
            <div v-if="selectedNode.type === 'condition'" class="ge-tip">
              本检查节点左侧有「上级」控制流端口：把某个
              <b>IF 条件节点</b>的「真分支 / 假分支」输出端口连到此处，该检查即只在执行合同时
              当对应 IF 条件成立 / 不成立时才执行（不成立则跳过，不阻塞）。拖 IF 的「真分支 /
              假分支」端口 → 点本节点的「上级」端口即可连线。
            </div>
          </template>

          <!-- 条件 IF -->
          <template v-else-if="selectedNode.type === 'if'">
            <div class="ge-tip">
              把「条件」端口连到数值节点；「真分支/假分支」输出端口连到子效果/控制流的「上级」端口。
            </div>
          </template>

          <!-- 列表/字典/算术运算 -->
          <template
            v-else-if="
              selectedNode.type === 'list-op' ||
              selectedNode.type === 'dict-op' ||
              selectedNode.type === 'calc' ||
              selectedNode.type === 'compare'
            "
          >
            <el-form label-width="80px" size="small">
              <el-form-item label="运算">
                <el-select v-model="selectedNode.data.op" style="width: 100%" @change="onOpChange">
                  <el-option
                    v-for="o in opOptions"
                    :key="o"
                    :label="OP_LABELS_FULL[o] || o"
                    :value="o"
                  />
                </el-select>
              </el-form-item>
              <el-form-item v-for="h in opArgs" :key="h" :label="OP_ARG_LABELS[h] || h">
                <el-input v-model="selectedNode.data.argLiterals[h]" placeholder="字面量(可选)" />
              </el-form-item>
            </el-form>
            <div class="ge-tip">
              把各参数输入端口连到数值节点；未连线的参数取上方字面量。计算节点：值A / 值B
              分别连两个数值源，输出连到效果「值 / 值2」或检查「值1 / 值2」。
            </div>
            <div v-if="selectedNode.type === 'compare'" class="ge-tip">
              这是「输出布尔值的条件式」：值A / 值B 分别连两个数值源，输出「布尔」连到
              <strong>条件(IF)</strong> 节点的「条件」端口，驱动真 / 假分支。等式 / 不等式结果即布尔值。
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

    <!-- 试算面板 -->
    <el-drawer v-model="showTrial" title="合同试算面板" direction="rtl" size="420px" append-to-body>
      <el-form label-width="80px" size="small">
        <el-form-item label="测试公司">
          <el-select v-model="trialCompanyId" placeholder="选择公司" filterable style="width: 100%">
            <el-option v-for="c in trialCompanies" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="trialRunning" @click="runTrial">运行试算</el-button>
        </el-form-item>
      </el-form>
      <template v-if="trialResults">
        <el-divider>检查结果</el-divider>
        <div v-if="trialResults.checks.length === 0" class="ge-tip">无检查条件</div>
        <div v-for="(chk, i) in trialResults.checks" :key="i" class="ge-trial-check">
          <span :class="chk.passed ? 'ge-trial-pass' : 'ge-trial-fail'">
            {{ chk.passed ? '✓' : '✗' }}
          </span>
          <span>{{ chk.label || chk.kind }}</span>
          <span v-if="!chk.passed && chk.errorMessage" class="ge-trial-err">{{ chk.errorMessage }}</span>
        </div>
        <el-divider>效果预览</el-divider>
        <div v-if="trialResults.effects.length === 0" class="ge-tip">无效果变更</div>
        <div v-for="(eff, i) in trialResults.effects" :key="i" class="ge-trial-effect">
          <span class="ge-trial-field">{{ eff.fieldKey }}</span>
          <span class="ge-trial-op">{{ getTrialEffectDisplay(eff) }}</span>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from "vue";
import { ElMessage } from "element-plus";
import { useGraphViewport } from "@/composables/useGraphViewport";
import {
  GGraph,
  GNode,
  GNodeType,
  NODE_META,
  nodeOutputs,
  graphToFlat,
  flatToGraph,
  OP_ARG_SPECS,
  OP_LABELS_FULL,
  OP_ARG_LABELS,
  ARITH_OPS,
  ENTITY_TYPES,
  ENTITY_TYPE_LABEL,
  ENTITY_FIELDS,
  INPUT_PORT_LABEL,
  PORT_DESC,
  PORT_HANDLE_TO_LABEL,
  portDataType,
  inputOutType,
  nodeInputHandles,
  FIELD_OPS,
  FIELD_OP_LABEL,
  VALUE_OPS,
  VALUE_OP_LABEL,
  COMPARE_OPS,
  COMPARE_OP_LABEL,
  VALUE_COMPARE_OPS,
  DICT_COMPARE_OPS,
  LIST_COMPARE_OPS,
  BOOL_COMPARE_OPS,
  VALUE_TYPES,
  VALUE_TYPE_LABEL,
  COND_KINDS,
  COND_KIND_LABEL,
  edgeTypeCheck,
} from "@/contracts/graph-model";
import { contractTypesApi, industryTypesApi, mapsApi, companiesApi, getErrorMessage } from "@/api";
import { toPinyinKey } from "@/utils/pinyin";

const props = defineProps<{ contractType?: any | null }>();
const emit = defineEmits<{ (e: "close"): void; (e: "saved"): void }>();

// ===== 几何常量 =====
const NODE_W = 288;
const COL_W = 118; // 输入/输出各占一栏，避免两侧说明挤撞
const HEADER_H = 30;
const PORT_TOP = 20;
const PORT_GAP = 50; // 加大间距，给端口下方的用途说明留两行空间
const DOT = 12;
const PORT_INSET = 12; // 端口圆心距节点边距，保证端口整体落在节点内部

// 根据所选实体类型动态列出其真实字段（value=真实字段名，label=中文）。
const entityFields = computed<{ key: string; label: string }[]>(
  () => ENTITY_FIELDS[selectedNode.value?.data?.entityType as string] || [],
);
function onEntityTypeChange() {
  // 切换实体后，原属性字段很可能不存在，清空避免写入无效字段。
  if (selectedNode.value) selectedNode.value.data.attribute = "";
}

const graph = reactive<GGraph>({ nodes: [], edges: [] });
const selectedId = ref<string | null>(null);
const pending = ref<{ nodeId: string; handle: string } | null>(null);
const industryTypes = ref<any[]>([]);
const meta = reactive({
  id: null as number | null,
  key: "",
  name: "",
  enabled: true,
});
const showSource = ref(false);
const saving = ref(false);
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
        const role = (n.data?.role || "").toLowerCase();
        return summary.includes(q) || label.includes(q) || key.includes(q) || role.includes(q);
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

// ===== 折叠/展开（IF/FOREACH 节点） =====
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
      if (e.source === cur && (e.sourceHandle === "then" || e.sourceHandle === "else" || e.sourceHandle === "body")) {
        if (!visited.has(e.target)) {
          visited.add(e.target);
          queue.push(e.target);
        }
      }
    }
  }
  return visited.size;
}
/** 判断某节点是否在某个已折叠的 IF/FOREACH 子树中（应被隐藏） */
function isHiddenByFold(nodeId: string): boolean {
  // BFS 从该节点向上找 parent 边，看是否最终到达某个 collapsed 节点
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
/** 判断某条边是否应被隐藏（源或目标被折叠隐藏） */
function isEdgeHiddenByFold(edge: any): boolean {
  return isHiddenByFold(edge.source) || isHiddenByFold(edge.target);
}
/** 可见节点列表（排除被折叠隐藏的） */
const visibleNodes = computed(() => graph.nodes.filter((n) => !isHiddenByFold(n.id)));
/** 可见边列表（排除被折叠隐藏的） */
const visibleEdges = computed(() => graph.edges.filter((e) => !isEdgeHiddenByFold(e)));

// ===== 自动布局（分层布局） =====
function applyAutoLayout() {
  const nodes = graph.nodes;
  if (!nodes.length) return;
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  // 构建邻接表（从 source → targets，沿连线方向）
  const children = new Map<string, string[]>();
  const parents = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (!children.has(e.source)) children.set(e.source, []);
    children.get(e.source)!.push(e.target);
    if (!parents.has(e.target)) parents.set(e.target, []);
    parents.get(e.target)!.push(e.source);
  }
  // BFS 分层：root/party 节点为 level 0，输入项 level 1，数值源/运算 level 2，效果/检查 level 3+
  const levels = new Map<string, number>();
  const queue: string[] = [];
  // 找根节点和参与方节点（没有入边的节点，或 type 为 root/party）
  for (const n of nodes) {
    if (n.type === "root" || n.type === "party" || !parents.has(n.id)) {
      levels.set(n.id, 0);
      queue.push(n.id);
    }
  }
  // BFS 分层
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
  // 未被 BFS 访问到的节点（孤立节点），分配到 level 1
  for (const n of nodes) {
    if (!levels.has(n.id)) levels.set(n.id, 1);
  }
  // 按层分组
  const levelGroups = new Map<number, GNode[]>();
  for (const n of nodes) {
    const lv = levels.get(n.id)!;
    if (!levelGroups.has(lv)) levelGroups.set(lv, []);
    levelGroups.get(lv)!.push(n);
  }
  // 排列：每层水平间距 280px，层内垂直间距 140px
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
// Ctrl+F 快捷键
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
const formulaInputRefs = ref<any>({});
function getFormulaFieldKeys(): string[] {
  return graph.nodes.filter((n) => n.type === "input" && n.data?.key).map((n) => n.data.key);
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
  const allItems = [
    ...fieldKeys,
    ...formulaFunctions.map((f) => f.key),
  ];
  const filtered = word
    ? allItems.filter((item) => item.toLowerCase().startsWith(word.toLowerCase()))
    : allItems;
  if (!filtered.length) {
    formulaAutocomplete.value.show = false;
    return;
  }
  const rect = ta.getBoundingClientRect();
  formulaAutocomplete.value = {
    show: true,
    items: filtered,
    x: rect.left,
    y: rect.bottom,
  };
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

// ===== 试算面板 =====
const showTrial = ref(false);
const trialCompanies = ref<any[]>([]);
const trialCompanyId = ref<number | null>(null);
const trialRunning = ref(false);
const trialResults = ref<{ checks: any[]; effects: any[] } | null>(null);
async function openTrial() {
  showTrial.value = true;
  trialResults.value = null;
  try {
    const res: any = await companiesApi.list();
    trialCompanies.value = Array.isArray(res) ? res : res?.items || [];
  } catch {
    trialCompanies.value = [];
  }
}
async function runTrial() {
  if (!trialCompanyId.value) {
    ElMessage.warning("请选择测试公司");
    return;
  }
  trialRunning.value = true;
  trialResults.value = null;
  try {
    const api = (await import("@/api")).default;
    const res: any = await api.post("/contracts/trial", {
      contractTypeId: meta.id,
      companyId: trialCompanyId.value,
    });
    trialResults.value = {
      checks: res.checks || [],
      effects: res.effects || [],
    };
  } catch (e: any) {
    ElMessage.error("试算失败：" + (e.message || "未知错误"));
  } finally {
    trialRunning.value = false;
  }
}
function getTrialEffectDisplay(effect: any): string {
  const op = effect.op || "ADD";
  const v = effect.value ?? 0;
  if (op === "SET") return `= ${v}`;
  if (op === "ADD") return `+ ${v}`;
  if (op === "SUB") return `- ${v}`;
  return `${op} ${v}`;
}

const listOps = Object.keys(OP_ARG_SPECS).filter(
  (k) => !k.startsWith("DICT_") && !ARITH_OPS.includes(k),
);
const dictOps = Object.keys(OP_ARG_SPECS).filter((k) => k.startsWith("DICT_"));
// 当前所选运算节点的可选 op 列表（list-op / dict-op / calc 共用同一面板）。
const opOptions = computed<string[]>(() => {
  const t = selectedNode.value?.type;
  if (t === "dict-op") return dictOps;
  if (t === "calc") return ARITH_OPS;
  if (t === "compare") return BOOL_COMPARE_OPS;
  return listOps;
});

const selectedNode = computed(() => graph.nodes.find((n) => n.id === selectedId.value) || null);

// 当前选中的输入项是否挂在某个 IF 分支之下（用于属性面板只读展示）。
const selectedInputBranch = computed(() => {
  const n = selectedNode.value;
  if (!n || n.type !== "input") return null;
  const be = graph.edges.find((e) => e.target === n.id && e.targetHandle === "parent");
  if (!be) return null;
  const src = nodeById(be.source);
  if (!src || src.type !== "if") return null;
  return { port: be.sourceHandle === "else" ? "假分支(else)" : "真分支(then)" };
});

// 当前选中的检查是否挂在某个 IF 分支之下（用于属性面板只读展示）。
const selectedConditionBranch = computed(() => {
  const n = selectedNode.value;
  if (!n || n.type !== "condition") return null;
  const be = graph.edges.find((e) => e.target === n.id && e.targetHandle === "parent");
  if (!be) return null;
  const src = nodeById(be.source);
  if (!src || src.type !== "if") return null;
  return { port: be.sourceHandle === "else" ? "假分支(else)" : "真分支(then)" };
});

const palette = [
  {
    group: "声明",
    items: [
      { type: "party" as GNodeType, title: "参与方" },
      { type: "input" as GNodeType, title: "输入项" },
    ],
  },
  {
    group: "数值",
    items: [
      { type: "value" as GNodeType, title: "数值源" },
      { type: "calc" as GNodeType, title: "计算" },
      { type: "compare" as GNodeType, title: "布尔比较" },
      { type: "list-op" as GNodeType, title: "列表运算" },
      { type: "dict-op" as GNodeType, title: "字典运算" },
    ],
  },
  {
    group: "业务",
    items: [
      { type: "effect" as GNodeType, title: "效果" },
      { type: "condition" as GNodeType, title: "检查" },
    ],
  },
  {
    group: "控制流",
    items: [
      { type: "if" as GNodeType, title: "条件(IF)" },
    ],
  },
];

let _seq = 0;
function uid(p = "n"): string {
  _seq += 1;
  return `${p}_${Date.now().toString(36)}_${_seq}`;
}

function nodeById(id?: string): GNode | undefined {
  if (!id) return undefined;
  return graph.nodes.find((n) => n.id === id);
}

// 输入端口（value 节点按来源类型只显示相关端口）
function inputHandles(node: GNode): string[] {
  return nodeInputHandles(node);
}
function outputHandles(node: GNode): string[] {
  if (node.type === "root") return [];
  return nodeOutputs(node);
}

function portLabel(node: GNode, kind: "in" | "out", idx: number): string {
  if (kind === "in") {
    const handle = inputHandles(node)[idx];
    if (node.type === "value") {
      return INPUT_PORT_LABEL[handle] || PORT_HANDLE_TO_LABEL[handle] || handle || "";
    }
    // 非数值源节点：优先按端口 handle 取中文名（兼容检查/效果节点按 kind 动态显示端口）。
    return (
      PORT_HANDLE_TO_LABEL[handle] ||
      NODE_META[node.type].inputs[idx] ||
      INPUT_PORT_LABEL[handle] ||
      handle ||
      ""
    );
  }
  const handle = outputHandles(node)[idx];
  // 优先按端口 handle 取中文名（兼容输入节点动态增加的「碳排放合计」等端点），
  // 再回退到节点类型静态输出标签。
  return (
    PORT_HANDLE_TO_LABEL[handle] ||
    (NODE_META[node.type].outputs[idx] === "out"
      ? "输出"
      : NODE_META[node.type].outputs[idx]) ||
    ""
  );
}

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
  const list = kind === "in" ? inputHandles(node) : outputHandles(node);
  const idx = list.indexOf(handle);
  if (idx < 0) return null;
  const cy = portRelY(idx);
  const cx = kind === "in" ? PORT_INSET : NODE_W - PORT_INSET;
  return { x: node.x + cx, y: node.y + cy };
}
// 端口「名称 + 用途说明」信息块位置：输入端口在左栏、输出端口在右栏，互不挤撞
function infoStyle(kind: "in" | "out", idx: number) {
  const cy = portRelY(idx);
  const top = cy - 7 + "px";
  if (kind === "in") return { left: "22px", width: COL_W + "px", top };
  return { right: "22px", width: COL_W + "px", top };
}
function portHandle(node: GNode, kind: "in" | "out", idx: number): string {
  const list = kind === "in" ? inputHandles(node) : outputHandles(node);
  return list[idx] || "";
}
// 端口用途详细说明（来自 graph-model 的 PORT_DESC，按 handle 取）
function portDesc(node: GNode, kind: "in" | "out", idx: number): string {
  return PORT_DESC[portHandle(node, kind, idx)] || "";
}
// 端口数据类型标注（中文短标签），用于画布端口旁展示。
function portType(node: GNode, kind: "in" | "out", idx: number): string {
  const t = portDataType(node, kind, idx);
  // 数值源「输入项」端口：反查连到 key 端口的输入项节点，取其实类型更精确。
  if (kind === "out" && node.type === "value" && node.data.valueType === "INPUT") {
    const keyEdge = graph.edges.find(
      (e) => e.target === node.id && e.targetHandle === "key",
    );
    const src = keyEdge ? graph.nodes.find((n) => n.id === keyEdge.source) : undefined;
    if (src && src.type === "input") return inputOutType(src.data.type || "number");
  }
  return t;
}
// 端口悬停提示：名称（类型）+ 说明
function portTitle(node: GNode, kind: "in" | "out", idx: number): string {
  const label = portLabel(node, kind, idx);
  const type = portType(node, kind, idx);
  const desc = portDesc(node, kind, idx);
  const head = type ? `${label}（${type}）` : label;
  return desc ? `${head}：${desc}` : head;
}
function nodeStyle(node: GNode) {
  const inN = inputHandles(node).length;
  const outN = outputHandles(node).length;
  const portN = Math.max(inN, outN, 1);
  const h = HEADER_H + PORT_TOP + (portN - 1) * PORT_GAP + DOT + 14; // 包容所有端口（名称+类型）+ 底部留白
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
    const portN = Math.max(inputHandles(n).length, outputHandles(n).length, 1);
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
function nodeSummary(n: GNode): string {
  const d = n.data || {};
  switch (n.type) {
    case "party":
      return `${d.role || ""} ${d.isHost ? "(主办)" : ""}`;
    case "input": {
      const be = graph.edges.find((e) => e.target === n.id && e.targetHandle === "parent");
      let suffix = "";
      if (be) {
        const src = nodeById(be.source);
        if (src && src.type === "if") {
          suffix = be.sourceHandle === "else" ? " · IF·假分支" : " · IF·真分支";
        }
      }
      return `${d.key || ""} · ${d.type || "number"}${suffix}`;
    }
    case "value":
      if (d.valueType === "ENTITY") {
        const et = ENTITY_TYPE_LABEL[d.entityType as string] || d.entityType || "";
        const f = (ENTITY_FIELDS[d.entityType as string] || []).find((x) => x.key === d.attribute);
        return `实体·${et}${f ? "·" + f.label : ""}`;
      }
      if (d.valueType === "FIELD") {
        const f = fieldOptions.value.find((x) => x.value === d.fieldKey);
        return `产业字段现值·${f?.label || d.fieldKey || "未选字段"}`;
      }
      if (d.valueType === "INDUSTRY_IS") {
        const it = industryTypes.value.find((x: any) => x.id === d.industryTypeId);
        return `产业类型判断·${it ? it.name : (d.industryTypeId ?? "未选产业")}（布尔）`;
      }
      return VALUE_TYPE_LABEL[d.valueType as string] || d.valueType || "";
    case "effect":
      return `产业字段 ${FIELD_OP_LABEL[d.op as string] || d.op || ""} ${d.fieldKey || ""}${d.valueOp ? " · 组合(" + (VALUE_OP_LABEL[d.valueOp as string] || d.valueOp) + ")" : ""}`;
    case "condition": {
      let s: string;
      if (d.condKind === "INDUSTRY_IS") s = "限定产业类型";
      else if (d.condKind === "VALUE_COMPARE")
        s = `值1 ${COMPARE_OP_LABEL[d.op as string] || d.op || ""} 值2`;
      else if (d.condKind === "DICT_COMPARE")
        s = `字典1 ${COMPARE_OP_LABEL[d.op as string] || d.op || ""} 字典2`;
      else if (d.condKind === "LIST_COMPARE")
        s = `列表1 ${COMPARE_OP_LABEL[d.op as string] || d.op || ""} 列表2`;
      else s = `${COMPARE_OP_LABEL[d.op as string] || d.op || ""} ${d.fieldKey || ""}`;
      const be = graph.edges.find((e) => e.target === n.id && e.targetHandle === "parent");
      if (be && (be.sourceHandle === "then" || be.sourceHandle === "else"))
        s += ` · IF·${be.sourceHandle === "then" ? "真分支" : "假分支"}`;
      return s;
    }
    case "if":
      return "条件分支";
    case "foreach":
      return `遍历 ${d.var || "item"}`;
    case "assign":
      return `赋值 ${d.name || ""}`;
    case "list-op":
    case "dict-op":
    case "calc":
    case "compare":
      return OP_LABELS_FULL[d.op as string] || d.op || "";
    default:
      return "";
  }
}

// ===== 操作 =====
function select(id: string) {
  selectedId.value = id;
}
function addNode(type: GNodeType) {
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
    case "party":
      return {
        role: `party${graph.nodes.filter((n) => n.type === "party").length + 1}`,
        label: "",
        isHost: false,
        selectable: true,
        industryTypeId: undefined,
      };
    case "input":
      return {
        key: `field${graph.nodes.filter((n) => n.type === "input").length + 1}`,
        label: "",
        type: "number",
        entityType: undefined,
        required: false,
        default: null,
      };
    case "value":
      return { valueType: "CONST", nodeIds: [] };
    case "effect":
      return { effectKind: "FIELD", op: "ADD", fieldKey: "", valueOp: undefined };
    case "condition":
      return { condKind: "VALUE_COMPARE", op: "GTE", fieldKey: "", label: "", errorMessage: "" };
    case "if":
      return {};
    case "list-op":
      return { op: "LIST_LEN", argLiterals: {} };
    case "dict-op":
      return { op: "DICT_KEYS", argLiterals: {} };
    case "calc":
      return { op: "ADD", argLiterals: {} };
    case "compare":
      return { op: "CMP_EQ", argLiterals: {} };
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

// 连线类型是否不匹配（供画布红线渲染）。
function edgeBad(e: any): boolean {
  return !edgeTypeCheck(graph, e).ok;
}
// 连线悬停提示：不匹配给出原因，匹配则显示两端类型与删除提示。
function edgeTip(e: any): string {
  const r = edgeTypeCheck(graph, e);
  if (!r.ok) return `⚠ 类型不匹配：${r.reason}`;
  return `类型匹配：${r.sourceType} → ${r.targetType}（点击删除连线）`;
}
function onPortClick(nodeId: string, handle: string, kind: "in" | "out") {
  if (kind === "out") {
    pending.value =
      pending.value && pending.value.nodeId === nodeId && pending.value.handle === handle
        ? null
        : { nodeId, handle };
    return;
  }
  // 输入端口：完成连线
  if (!pending.value) return;
  if (pending.value.nodeId === nodeId) {
    pending.value = null;
    return;
  }
  const idx = graph.edges.findIndex((e) => e.target === nodeId && e.targetHandle === handle);
  if (idx >= 0) graph.edges.splice(idx, 1);
  const newEdge: any = {
    id: uid("e"),
    source: pending.value.nodeId,
    sourceHandle: pending.value.handle,
    target: nodeId,
    targetHandle: handle,
  };
  graph.edges.push(newEdge);
  pending.value = null;
  // 实时类型检查：新建连线若两端类型不匹配，立即预警（不强制拦截，仍可保存）。
  const chk = edgeTypeCheck(graph, newEdge);
  if (!chk.ok) ElMessage.warning(`连线类型不匹配：${chk.reason}`);
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
function onValueTypeChange() {
  if (selectedNode.value && !Array.isArray(selectedNode.value.data.nodeIds)) {
    selectedNode.value.data.nodeIds = [];
  }
}
// 数值源 CONST：一键将常量值设为空字典 {} / 空数组 []，用于输出空容器。
function setConstEmpty(kind: "dict" | "list") {
  if (!selectedNode.value) return;
  selectedNode.value.data.value = kind === "dict" ? "{}" : "[]";
}
// 输入项切换类型时：选「原料清单」自动关联实体=原料；字典/列表自动给出空对象/空数组默认。
function onInputTypeChange() {
  const n = selectedNode.value;
  if (!n || n.type !== "input") return;
  if (n.data.type === "materialList") {
    n.data.entityType = "MATERIAL";
    n.data.default = {};
  } else if (n.data.type === "partList") {
    n.data.entityType = "PART";
    n.data.default = {};
  } else if (n.data.type === "productList") {
    n.data.entityType = "PRODUCT";
    n.data.default = {};
  } else if (n.data.type === "infrastructureList") {
    n.data.entityType = "INFRASTRUCTURE";
    n.data.default = {};
  } else if (n.data.type === "fuelList") {
    n.data.entityType = "FUEL";
    n.data.default = {};
  } else if (n.data.type === "vehicleList") {
    n.data.entityType = "VEHICLE";
    n.data.default = {};
  } else if (n.data.type === "warehouseList") {
    n.data.entityType = "WAREHOUSE";
    n.data.default = {};
  } else if (n.data.type === "techNode") {
    n.data.entityType = "TECH_NODE";
    n.data.default = "";
  } else if (n.data.type === "dict") {
    n.data.default = {};
  } else if (n.data.type === "list") {
    n.data.default = [];
  } else {
    // 切回标量类型：清掉残留的对象/数组默认值，避免文本输入框显示 [object Object]
    if (n.data.default !== null && typeof n.data.default === "object") {
      n.data.default = null;
    }
  }
}
// 字典/列表字段的默认值以 JSON 文本呈现（避免 el-input 把对象渲染成 [object Object]）。
const defaultJsonText = computed(() => {
  const n = selectedNode.value;
  if (!n || n.type !== "input") return "";
  const d = n.data.default;
  if (d === undefined || d === null) return n.data.type === "dict" ? "{}" : "[]";
  return JSON.stringify(d);
});
function onDefaultJsonChange(val: string) {
  const n = selectedNode.value;
  if (!n || n.type !== "input") return;
  try {
    n.data.default = JSON.parse(val);
  } catch {
    ElMessage.warning("默认值不是合法 JSON");
  }
}
function onOpChange() {
  if (selectedNode.value) selectedNode.value.data.argLiterals = {};
}
// 字段类型中文短名（仅列表/字典会在下拉里额外标注，因为这两类用数值比较符时比的是长度）。
const FIELD_TYPE_SHORT: Record<string, string> = {
  STRING: "文本",
  NUMBER: "数字",
  BOOLEAN: "布尔",
  LIST: "列表",
  DICTIONARY: "字典",
};
const fieldOptions = computed(() => {
  const seen = new Set<string>();
  const out: { value: string; label: string; fieldType?: string; hidden?: boolean }[] = [];
  for (const it of industryTypes.value) {
    for (const f of it.fields || []) {
      const key = f.fieldKey as string;
      const name = (f.name || f.label || key) as string;
      if (!key) continue;
      const hidden = f.visible === false;
      // 去重键区分「显/隐」：产业类型管理处隐藏的字段，在合同编辑器的数据源（FIELD 值源 /
      // FIELD_COMPARE）里仍应可查看并选择；同名但一显一隐的字段用·隐藏标注区分，均可选。
      const dupKey = `${name}|${hidden}`;
      if (seen.has(dupKey)) continue;
      seen.add(dupKey);
      const tag =
        f.fieldType === "LIST" || f.fieldType === "DICTIONARY"
          ? ` [${FIELD_TYPE_SHORT[f.fieldType as string] || f.fieldType}]`
          : "";
      const hideTag = hidden ? "·隐藏" : "";
      out.push({ value: key, label: `${name}${tag}${hideTag}`, fieldType: f.fieldType, hidden });
    }
  }
  // 展示字段在前、隐藏字段在后，便于阅读。
  out.sort((a, b) => (a.hidden === b.hidden ? 0 : a.hidden ? 1 : -1));
  return out;
});

// 字段 key → 字段类型（用于检测列表/字典字段的「数值比较比的是长度」陷阱、
// 以及 FIELD 值源节点选字段后同步输出端口类型）。含隐藏字段：隐藏字段在数据源处仍可选，
// 其类型同样需解析，否则端口类型与连线类型校验会失效。
const fieldTypeByKey = computed<Record<string, string>>(() => {
  const map: Record<string, string> = {};
  for (const it of industryTypes.value) {
    for (const f of it.fields || []) {
      const key = f.fieldKey as string;
      if (key) map[key] = (f.fieldType as string) || "STRING";
    }
  }
  return map;
});

// FIELD 值源节点选字段后，同步 node.data.fieldType，使输出端口类型随字段数据类型变化。
function onFieldKeyChange(key: string) {
  if (!selectedNode.value) return;
  const f = fieldOptions.value.find((x) => x.value === key);
  selectedNode.value.data.fieldType = f?.fieldType || "";
}

// 产业类型加载后回填图里 FIELD 值源节点的 data.fieldType，
// 使重新打开编辑器时端口类型也能随字段类型正确显示、并参与连线类型校验。
watch(
  [industryTypes, () => graph.nodes],
  () => {
    if (!industryTypes.value.length) return;
    for (const n of graph.nodes) {
      if (n.type === "value" && (n.data.valueType || "INPUT") === "FIELD" && n.data.fieldKey) {
        n.data.fieldType = fieldTypeByKey.value[n.data.fieldKey] || "";
      }
    }
  },
  { deep: true, immediate: true },
);

// 「产业字段比较」(FIELD_COMPARE) 选中了列表/字典字段时给出告警：
// 数值比较符 (≥/≤/>/</=) 对列表/字典比较的是元素个数（长度），而非内部数值。
const fieldCompareLengthHint = computed(() => {
  const n = selectedNode.value;
  if (!n || n.type !== "condition" || n.data?.condKind !== "FIELD_COMPARE") return null;
  const key = (n.data?.fieldKey as string) || "";
  if (!key) return null;
  const ft = fieldTypeByKey.value[key];
  if (ft !== "LIST" && ft !== "DICTIONARY") return null;
  return { typeLabel: ft === "LIST" ? "列表" : "字典" };
});
const opArgs = computed(() =>
  selectedNode.value ? OP_ARG_SPECS[selectedNode.value.data.op as string] || [] : [],
);

const sourceJson = computed(() =>
  JSON.stringify(
    {
      partyRoles: graphToFlat(graph).partyRoles,
      inputSchema: graphToFlat(graph).inputSchema,
      effects: graphToFlat(graph).effects,
      conditions: graphToFlat(graph).conditions,
    },
    null,
    2,
  ),
);

// ===== 加载 / 保存 =====
function load(ct?: any | null) {
  const g = ct?.graph;
  let nodes: GNode[] = [];
  let edges: any[] = [];
  if (g && Array.isArray(g.nodes)) {
    nodes = JSON.parse(JSON.stringify(g.nodes));
    edges = JSON.parse(JSON.stringify(g.edges || []));
  } else {
    const fg = flatToGraph({
      partyRoles: ct?.partyRoles,
      inputSchema: ct?.inputSchema,
      effects: ct?.effects,
      conditions: ct?.conditions,
    });
    nodes = fg.nodes;
    edges = fg.edges;
  }
  graph.nodes = nodes;
  graph.edges = edges;
  meta.id = ct?.id ?? null;
  meta.key = ct?.key ?? "";
  meta.name = ct?.name ?? "";
  meta.enabled = ct?.enabled ?? true;
  selectedId.value = null;
  pending.value = null;
}
load(props.contractType);
watch(() => props.contractType, load);

// 新建时：输入名称实时用拼音自动生成 key（编辑态 key 只读，不覆盖）
watch(
  () => meta.name,
  () => {
    if (!meta.id) {
      meta.key = (meta.name || "").trim() ? toPinyinKey(meta.name.trim()) : "";
    }
  },
);

async function loadIndustryTypes() {
  try {
    const res: any = await industryTypesApi.list();
    industryTypes.value = Array.isArray(res) ? res : res?.items || [];
  } catch (e) {
    console.error(e);
  }
}
function toggleSource() {
  showSource.value = !showSource.value;
}
async function onSave() {
  const flat = graphToFlat(graph);
  // 保存前校验：产业字段(FIELD)效果必须连接「值」来源，否则引擎会按 0 累加，
  // 导致合同执行后"字段毫无变化"且无报错（此类静默失败难以排查）。
  const badEffects = (flat.effects || []).filter((e: any) => {
    if (e.kind !== "FIELD") return false;
    const v = e.value;
    const noValue =
      !v ||
      (v.type === "INPUT" && !v.key) ||
      (v.type === "CONST" && (v.value == null || String(v.value).trim() === ""));
    return noValue;
  });
  if (badEffects.length) {
    ElMessage.error(
      `存在 ${badEffects.length} 个「产业字段」效果未配置数值来源（值端口未连线或常量值为空），执行后不会改变任何字段。请为每个字段效果连接常量/输入/实体等数值节点后再保存。`,
    );
    saving.value = false;
    return;
  }
  const payload: any = {
    partyRoles: flat.partyRoles,
    inputSchema: flat.inputSchema,
    effects: flat.effects,
    conditions: flat.conditions,
    graph: JSON.parse(JSON.stringify(graph)),
  };
  saving.value = true;
  try {
    if (meta.id) {
      await contractTypesApi.update(meta.id, payload);
      ElMessage.success("已保存");
    } else {
      if (!meta.name) {
        ElMessage.warning("请填写名称");
        saving.value = false;
        return;
      }
      // key 兜底：新建时若尚未自动生成，按名称拼音生成
      if (!meta.key) {
        meta.key = toPinyinKey(meta.name.trim());
      }
      await contractTypesApi.create({
        key: meta.key,
        name: meta.name,
        ...payload,
      });
      ElMessage.success("已创建");
    }
    emit("saved");
  } catch (err: any) {
    ElMessage.error("保存失败：" + getErrorMessage(err));
  } finally {
    saving.value = false;
  }
}
function onClear() {
  graph.nodes = [];
  graph.edges = [];
  selectedId.value = null;
  pending.value = null;
}

onMounted(() => {
  loadIndustryTypes();
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
  /* 侧栏随窗口宽度轻微伸缩，剩余空间全部给中间画布 */
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
/* 类型不匹配的连线：红色虚线 + 闪烁，提示用户尽早修正。 */
.ge-edge-bad {
  stroke: #e74c3c !important;
  stroke-width: 3 !important;
  stroke-dasharray: 6 4;
  animation: ge-edge-blink 1s ease-in-out infinite;
}
@keyframes ge-edge-blink {
  0%,
  100% {
    stroke-opacity: 1;
  }
  50% {
    stroke-opacity: 0.35;
  }
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
  z-index: 1; /* 建立堆叠上下文，把内部端口/文字关在卡片内，避免穿透到其它节点之上 */
}
.ge-node-sel {
  outline: 2px solid #409eff;
  z-index: 10; /* 选中/拖拽中的节点置顶，压在其余节点之上 */
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
.ge-port-desc {
  font-size: 10px;
  line-height: 13px;
  color: #909399;
  word-break: break-all;
}
/* 右侧面板中的端口说明列表（画布上不再显示长描述，避免撑出节点框） */
.ge-port-desc-list {
  margin-top: 8px;
  border-top: 1px dashed #dcdfe6;
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ge-port-desc-title {
  font-size: 12px;
  font-weight: 600;
  color: #34495e;
}
.ge-port-desc-item {
  margin-top: 0 !important;
}
.ge-port-desc-type {
  flex: 0 0 auto;
  font-size: 10px;
  line-height: 13px;
  color: #409eff;
  background: #ecf5ff;
  border: 1px solid #d9ecff;
  border-radius: 3px;
  padding: 0 4px;
  margin-left: 4px;
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
.ge-tip-inline {
  font-size: 12px;
  color: #c0c4cc;
}
.ge-sub {
  font-size: 11px;
  color: #b0b3b8;
}
.ge-branch-on {
  font-size: 12px;
  color: #e67e22;
  font-weight: 600;
}
.ge-warn {
  margin-top: 8px;
}
.ge-node-desc {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px dashed #e4e7ed;
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

/* ===== 试算面板 ===== */
.ge-trial-check {
  padding: 4px 0;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ge-trial-pass {
  color: #67c23a;
  font-weight: bold;
}
.ge-trial-fail {
  color: #f56c6c;
  font-weight: bold;
}
.ge-trial-err {
  color: #909399;
  font-size: 11px;
}
.ge-trial-effect {
  padding: 3px 0;
  font-size: 12px;
  display: flex;
  gap: 8px;
}
.ge-trial-field {
  font-weight: 600;
  color: #303133;
}
.ge-trial-op {
  color: #409eff;
  font-family: monospace;
}
</style>
