<template>
  <div class="contract-manager">
    <div class="mm-toolbar">
      <h2 class="mm-title">{{ authStore.can("contract:manage") ? "合同管理" : "合同" }}</h2>
      <div class="mm-actions">
        <el-input
          v-model="searchText"
          placeholder="搜索合同编号或类型"
          clearable
          style="width: 200px"
        />
        <el-button
          v-if="authStore.can('contract:manage')"
          type="primary"
          @click="openCreate"
          >+ 新建</el-button
        >
      </div>
    </div>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-alert
      v-if="canOperateContracts && filteredContracts.length > 0 && !hasDraft"
      type="info"
      show-icon
      :closable="false"
      title="暂无草稿合同可执行"
      description="新建合同默认保存为「草稿」，填写完整参与方合同编号后，即可点击「执行」落账。"
      style="margin-bottom: 12px"
    />

    <el-table v-loading="loading" :data="filteredContracts" border stripe style="width: 100%">
      <template #empty>
        <el-empty
          :description="authStore.can('contract:manage') ? '暂无合同，点击右上角「+ 新建」创建草稿' : '暂无合同'"
        >
          <el-button v-if="authStore.can('contract:manage')" type="primary" @click="openCreate"
            >+ 新建合同</el-button
          >
        </el-empty>
      </template>
      <el-table-column label="合同编号" min-width="220">
        <template #default="{ row }">{{ contractNumbersText(row) }}</template>
      </el-table-column>
      <el-table-column label="类型" min-width="200">
        <template #default="{ row }">{{ row.contractType?.name || "—" }}</template>
      </el-table-column>
      <el-table-column label="状态" width="150" align="center">
        <template #default="{ row }">
          <el-tooltip :content="statusHint(row)" placement="top">
            <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="参与方" min-width="200">
        <template #default="{ row }">
          <div class="party-boxes">
            <span
              v-for="(p, i) in parseJson(row.parties, [])"
              :key="i"
              class="party-box"
              :class="{ 'party-box--host': p.isHost }"
              :title="p.isHost ? '主席团（主办方）' : '参与公司'"
            >
              {{ p.isHost ? "主席团" : p.companyName || companyName(p.companyId) || ("公司#" + p.companyId) }}
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="160">
        <template #default="{ row }">{{ $formatTime(row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button
            size="small"
            type="success"
            :disabled="executeBtnState(row).disabled"
            :title="executeBtnState(row).title"
            @click="executeContract(row)"
            >执行</el-button
          >
          <el-button
            v-if="authStore.isSuperAdmin"
            size="small"
            type="danger"
            @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建合同 -->
    <el-dialog append-to-body v-model="showCreate" title="新建合同" width="640px">
      <el-form label-width="130px">
        <el-form-item label="合同类型" required>
          <el-select
            v-model="createForm.contractTypeId"
            filterable
            placeholder="选择合同类型"
            style="width: 100%"
            @change="onTypeChange"
          >
            <el-option v-for="t in contractTypes" :key="t.id" :label="t.name" :value="t.id" />
          </el-select>
        </el-form-item>
        <template v-if="selectedType">
          <el-form-item
            v-for="p in partyRolesAll"
            :key="p.role"
            :label="p.label"
            :required="!p.isHost"
          >
            <template v-if="!p.isHost">
              <div class="party-row">
                <el-select
                  v-model="createForm.parties[p.role]"
                  filterable
                  placeholder="选择公司"
                  style="flex: 1"
                >
                  <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
                </el-select>
                <el-input
                  v-model="partyNumbers[p.role]"
                  placeholder="合同编号"
                  style="width: 160px"
                />
              </div>
            </template>
            <template v-else>
              <span class="host-hint">主席团</span>
            </template>
          </el-form-item>

          <el-divider>合同数据</el-divider>
          <el-form-item
            v-for="field in visibleInputSchemaFields"
            :key="field.key"
            :label="field.label"
            :required="field.required"
            :label-position="field.type === 'materialList' || field.type === 'partList' || field.type === 'productList' || field.type === 'infrastructureList' || field.type === 'fuelList' || field.type === 'vehicleList' || field.type === 'warehouseList' || field.type === 'techNode' || field.type === 'mapNode' || field.type === 'nodeRoute' ? 'top' : undefined"
          >
            <el-select
              v-if="field.type === 'ENTITY'"
              v-model="createForm.inputs[field.key]"
              filterable
              placeholder="选择数据实体"
              style="width: 100%"
              @focus="loadEntityOptions(field.entityType)"
            >
              <el-option
                v-for="opt in entityOptions(field.entityType)"
                :key="opt.id"
                :label="opt.name"
                :value="opt.id"
              />
            </el-select>
            <el-input-number
              v-else-if="field.type === 'number'"
              v-model="createForm.inputs[field.key]"
              :min="0"
              style="width: 100%"
            />
            <div v-else-if="field.type === 'nodeRoute'" class="route-editor">
              <div v-if="(createForm.inputs[field.key] || []).length" class="route-chips">
                <span
                  v-for="(id, idx) in createForm.inputs[field.key] || []"
                  :key="field.key + '-' + id + '-' + idx"
                  class="route-chip"
                >
                  <b class="route-idx">{{ idx + 1 }}</b>
                  <span class="route-name">{{ mapNodeName(id) }}</span>
                  <span class="route-ops">
                    <el-button
                      link
                      size="small"
                      :disabled="idx === 0"
                      title="上移"
                      @click="moveRouteNode(field.key, idx, -1)"
                      >↑</el-button
                    >
                    <el-button
                      link
                      size="small"
                      :disabled="idx === routeLen(field.key) - 1"
                      title="下移"
                      @click="moveRouteNode(field.key, idx, 1)"
                      >↓</el-button
                    >
                    <el-button
                      link
                      size="small"
                      type="danger"
                      title="移除"
                      @click="removeRouteNode(field.key, id)"
                      >✕</el-button
                    >
                  </span>
                </span>
              </div>
              <el-select
                v-model="routeAddVal"
                filterable
                clearable
                placeholder="+ 添加节点"
                style="width: 100%"
                @change="(v: number | null) => addRouteNode(field.key, v)"
              >
                <el-option
                  v-for="m in addableMapNodes(field.key)"
                  :key="m.id"
                  :label="`${m.name}(${m.region || '-'})`"
                  :value="m.id"
                />
              </el-select>
              <div class="ge-tip">按路程顺序逐个添加地图节点（至少 2 个，可任意多个）。</div>
            </div>
            <div v-else-if="field.type === 'list'" class="list-editor">
              <div v-for="(it, i) in createForm.inputs[field.key] || []" :key="i" class="list-row">
                <el-input-number
                  v-if="field.elementType === 'number'"
                  v-model="createForm.inputs[field.key][i]"
                  :min="0"
                  controls-position="right"
                />
                <el-input v-else v-model="createForm.inputs[field.key][i]" placeholder="元素值" />
                <el-button size="small" type="danger" plain @click="removeListItem(field.key, i)"
                  >×</el-button
                >
              </div>
              <el-button size="small" @click="addListItem(field.key, field.elementType)"
                >+ 添加元素</el-button
              >
            </div>
            <div v-else-if="field.type === 'dict'" class="list-editor">
              <div v-for="(v, k) in createForm.inputs[field.key] || {}" :key="k" class="list-row">
                <el-input
                  :model-value="k"
                  placeholder="键"
                  @change="(nv: string) => renameDictKey(field.key, String(k), nv)"
                />
                <el-input-number
                  v-if="field.elementType === 'number'"
                  v-model="createForm.inputs[field.key][k]"
                  :min="0"
                  controls-position="right"
                />
                <el-input v-else v-model="createForm.inputs[field.key][k]" placeholder="值" />
                <el-button
                  size="small"
                  type="danger"
                  plain
                  @click="removeDictEntry(field.key, String(k))"
                  >×</el-button
                >
              </div>
              <el-button size="small" @click="addDictEntry(field.key)">+ 添加键值</el-button>
            </div>
            <div v-else-if="field.type === 'materialList' || field.type === 'partList' || field.type === 'productList' || field.type === 'infrastructureList' || field.type === 'fuelList' || field.type === 'vehicleList' || field.type === 'warehouseList'" class="material-editor">
              <el-select
                :model-value="materialKeys(field.key)"
                multiple
                filterable
                :placeholder="field.type === 'partList' ? '选择零件' : (field.type === 'productList' ? '选择产品' : (field.type === 'infrastructureList' ? '选择基建' : (field.type === 'fuelList' ? '选择燃料' : (field.type === 'vehicleList' ? '选择载具' : (field.type === 'warehouseList' ? '选择仓库' : '选择原料')))))"
                style="width: 100%"
                @focus="loadEntityOptions(field.entityType || entityTypeForFieldType(field.type))"
                @change="onMaterialSelectChange(field.key, $event)"
              >
                <el-option
                  v-for="opt in listOptions(field)"
                  :key="opt.id"
                  :label="opt.name"
                  :value="opt.name"
                />
              </el-select>
              <div v-if="field.type === 'infrastructureList' && infraFilterHint(field)" class="loc-hint">
                {{ infraFilterHint(field) }}
              </div>
              <div v-if="field.type === 'vehicleList' && vehicleFilterHint(field)" class="loc-hint">
                {{ vehicleFilterHint(field) }}
              </div>
              <div v-if="materialKeys(field.key).length" class="material-qty">
                <div
                  v-for="name in materialKeys(field.key)"
                  :key="field.key + '-' + name"
                  class="material-qty-row"
                >
                  <span class="material-name">{{ name }}</span>
                  <el-input-number
                    v-model="createForm.inputs[field.key][name]"
                    :min="0"
                    :step="1"
                    controls-position="right"
                    style="width: 160px"
                  />
                  <el-button
                    size="small"
                    type="danger"
                    plain
                    @click="removeMaterial(field.key, name)"
                    >×</el-button
                  >
                </div>
              </div>
            </div>
            <div v-else-if="field.type === 'mapNode'" class="dashed-box">
              <el-select
                v-model="createForm.inputs[field.key]"
                filterable
                clearable
                placeholder="选择所在地图节点"
                style="width: 100%"
                @focus="loadMapNodes()"
              >
                <el-option
                  v-for="m in mapNodes"
                  :key="m.id"
                  :label="`${m.name}（${m.region || '-'}）`"
                  :value="m.name"
                />
              </el-select>
            </div>
            <div v-else-if="field.type === 'techNode'" class="dashed-box">
              <el-select
                v-model="createForm.inputs[field.key]"
                filterable
                clearable
                placeholder="选择科技树节点"
                style="width: 100%"
                @focus="loadTechNodes()"
              >
                <el-option
                  v-for="t in techNodes"
                  :key="t.id"
                  :label="`${t.name}（研发 ${t.researchCost ?? 0}）`"
                  :value="t.name"
                />
              </el-select>
            </div>
            <el-input v-else v-model="createForm.inputs[field.key]" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleCreate">确定创建</el-button>
      </template>
    </el-dialog>

    <!-- 合同详情 -->
    <el-dialog append-to-body v-model="showDetail" :title="`合同详情 · ${detailRow?.name || ''}`" width="720px">
      <template v-if="detailRow">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="合同类型">{{
            detailRow.contractType?.name
          }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{
            statusLabel(detailRow.status)
          }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{
            $formatTime(detailRow.createdAt)
          }}</el-descriptions-item>
          <el-descriptions-item label="执行时间">{{
            detailRow.executedAt ? $formatTime(detailRow.executedAt) : "—"
          }}</el-descriptions-item>
        </el-descriptions>

        <el-divider>参与方</el-divider>
        <el-table :data="detailParties" border size="small">
          <el-table-column label="公司">
            <template #default="{ row }">
              {{
                row.isHost
                  ? "主席团"
                  : row.companyName || companyName(row.companyId) || `公司#${row.companyId}`
              }}
            </template>
          </el-table-column>
          <el-table-column label="合同编号" min-width="220">
            <template #default="{ row }">
              <template v-if="row.isHost">—</template>
              <template v-else-if="canEditParty(row) && editingNumber.role === row.role">
                <div class="party-row">
                  <el-input v-model="editingNumber.value" placeholder="输入合同编号" style="flex: 1" />
                  <el-button size="small" type="primary" :loading="submitting" @click="saveNumber(row)"
                    >保存</el-button
                  >
                  <el-button size="small" @click="cancelEditNumber">取消</el-button>
                </div>
              </template>
              <template v-else-if="canEditParty(row)">
                <div class="party-row">
                  <span :class="{ 'num-empty': !row.contractNumber }">{{
                    row.contractNumber || "未编号"
                  }}</span>
                  <el-button size="small" link type="primary" @click="startEditNumber(row)"
                    >补全/修改</el-button
                  >
                </div>
              </template>
              <template v-else>
                <span :class="{ 'num-empty': !row.contractNumber }">{{
                  row.contractNumber || "未编号"
                }}</span>
              </template>
            </template>
          </el-table-column>
        </el-table>

        <el-divider>输入参数</el-divider>
        <el-table :data="detailInputs" border size="small">
          <el-table-column prop="key" label="参数" width="160" />
          <el-table-column prop="label" label="名称" width="200" />
          <el-table-column label="值">
            <template #default="{ row }">{{ formatInputValue(row) }}</template>
          </el-table-column>
        </el-table>

        <template v-if="detailChecks && detailChecks.length">
          <el-divider>检查结果</el-divider>
          <el-table :data="detailChecks" border size="small">
            <el-table-column prop="label" label="检查项" min-width="200" :formatter="condKindFmt" />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag :type="row.passed ? 'success' : 'danger'">{{
                  row.passed ? "通过" : "未通过"
                }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="detail" label="详情" min-width="240" />
          </el-table>
        </template>
        <template v-if="execLogRows.length">
          <el-divider>执行结果</el-divider>
          <el-alert
            v-if="execLogRows.every((r) => r.before === r.after)"
            type="warning"
            :closable="false"
            title="本次执行未对任何产业字段产生实际变化"
            description="常见原因：效果的「值」来源未连接（导致按 0 累加）、或前置检查已阻止落账。请打开合同类型编辑器检查效果节点是否连了数值来源。"
            style="margin-bottom: 12px"
          />
          <el-table :data="execLogRows" border size="small">
            <el-table-column prop="company" label="公司" min-width="160" />
            <el-table-column prop="field" label="字段" min-width="140" />
            <el-table-column prop="op" label="操作" width="80" />
            <el-table-column label="前值" min-width="110">
              <template #default="{ row }">{{ row.before }}</template>
            </el-table-column>
            <el-table-column label="后值" min-width="110">
              <template #default="{ row }">{{ row.after }}</template>
            </el-table-column>
          </el-table>
        </template>
      </template>
    </el-dialog>

    <!-- 预检结果（亦作为「创建即执行」失败时的错误窗口） -->
    <el-dialog append-to-body v-model="showPrecheck" title="合同前置检查未通过" width="680px">
      <el-alert
        v-if="precheckResults.length"
        :type="precheckAllPass ? 'success' : 'error'"
        :closable="false"
        :title="precheckAllPass ? '全部检查通过，可以执行' : '存在未通过的检查，执行将被中止'"
      />
      <el-table
        v-loading="prechecking"
        :data="precheckResults"
        border
        size="small"
        style="margin-top: 12px"
      >
        <el-table-column prop="label" label="检查项" min-width="200" :formatter="condKindFmt" />
        <el-table-column label="结果" width="90">
          <template #default="{ row }">
            <el-tag :type="row.passed ? 'success' : 'danger'">{{
              row.passed ? "通过" : "未通过"
            }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="详情" min-width="260" />
      </el-table>
      <template #footer>
        <el-button @click="showPrecheck = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 该产业不支持该合同：所选参与方公司产业缺少效果字段 -->
    <el-dialog append-to-body v-model="showUnsupported" title="该产业不支持该合同" width="620px">
      <el-alert
        type="error"
        :closable="false"
        title="所选参与方公司所属产业缺少合同所需字段，无法创建该合同"
      />
      <el-table :data="missingEffectFields" border size="small" style="margin-top: 12px">
        <el-table-column label="参与方" width="140">
          <template #default="{ row }">{{ partyLabel(row.party) }}</template>
        </el-table-column>
        <el-table-column prop="companyName" label="公司" min-width="160" />
        <el-table-column label="缺失字段" min-width="200">
          <template #default="{ row }">{{ row.fieldName }}（{{ row.fieldKey }}）</template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button type="primary" @click="showUnsupported = false">我知道了</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onUnmounted } from "vue";
import { useCompetitionStore } from "@/stores/competition";
import { useCompetitionReload } from "@/composables/useCompetitionReload";
import { onRealtime, offRealtime } from "@/realtime/socket";
import { useResourceChanged } from "@/realtime/useResourceChanged";
import { useAuthStore } from "@/stores/auth";
import { contractTypesApi, contractsApi, mapsApi, companyFieldsApi, industryTypesApi } from "@/api";
import { evalFormCondition, type FormConditionCtx } from "@/contracts/graph-model";
import api from "@/api/request";
import { ElMessage, ElMessageBox } from "element-plus";
import { formatTime } from "@/utils/format";

const compStore = useCompetitionStore();
const authStore = useAuthStore();

const contracts = ref<any[]>([]);
const contractTypes = ref<any[]>([]);
const companies = ref<any[]>([]);
const loading = ref(false);
const searchText = ref("");
const submitting = ref(false);

const showCreate = ref(false);
const showDetail = ref(false);
const detailRow = ref<any>(null);

const showPrecheck = ref(false);
const prechecking = ref(false);
const precheckResults = ref<any[]>([]);
// 选参与方后校验：所选公司产业缺少效果字段时弹出的错误界面。
const showUnsupported = ref(false);

const partyNumbers = reactive<Record<string, string>>({});

// 详情页内联补编号编辑态：{ role: 正在编辑的参与方角色, value: 输入框当前值 }
const editingNumber = reactive<{ role: string | null; value: string }>({ role: null, value: "" });

const createForm = reactive({
  contractTypeId: undefined as number | undefined,
  parties: {} as Record<string, number>,
  inputs: {} as Record<string, any>,
});

const selectedType = computed(
  () => contractTypes.value.find((t: any) => t.id === createForm.contractTypeId) || null,
);

const partyRolesSelectable = computed(() => {
  const roles = parseJson(selectedType.value?.partyRoles, []);
  return roles.filter((p: any) => !p.isHost);
});
// 全部角色（含主办方），用于新建表单透出主办方一方（仅展示，无需公司与编号）
const partyRolesAll = computed(() => parseJson(selectedType.value?.partyRoles, []));
const inputSchemaFields = computed(() => parseJson(selectedType.value?.inputSchema, []));
// 按 IF 分支条件过滤后实际可见的输入项（创建表单只渲染可见字段）。
const visibleInputSchemaFields = computed(() =>
  inputSchemaFields.value.filter((f: any) => isFieldVisible(f)),
);

// 公司 → 产业类型 id 映射（用于按参与方产业类型判定 IF 条件）。
const companyIndustryMap = computed<Record<number, number | null>>(() => {
  const m: Record<number, number | null> = {};
  for (const c of companies.value) m[c.id] = c.industryTypeId ?? null;
  return m;
});

// 产业类型字段集合（含隐藏字段）：industryTypeId → Set<fieldKey>。
// 用于选参与方后校验「合同效果所引用的字段」在该公司所属产业中是否存在。
const industryTypes = ref<any[]>([]);
const industryFieldKeyMap = computed<Map<number, Set<string>>>(() => {
  const m = new Map<number, Set<string>>();
  for (const it of industryTypes.value) {
    const set = new Set<string>();
    for (const f of it.fields || []) if (f.fieldKey) set.add(f.fieldKey);
    m.set(it.id, set);
  }
  return m;
});

// 从合同类型的效果树递归收集叶子「产业字段」效果引用的 (party, fieldKey)。
// 效果树结构：{kind:"FIELD",party,fieldKey,...} / IF{then,else} / FOREACH{body} / ASSIGN（无子效果）。
function collectEffectFieldRefs(
  effects: any[],
  out: { party: string; fieldKey: string }[] = [],
): { party: string; fieldKey: string }[] {
  for (const e of effects || []) {
    if (!e || typeof e !== "object") continue;
    if (e.kind === "FIELD") out.push({ party: e.party || "", fieldKey: e.fieldKey || "" });
    else if (e.kind === "IF") {
      collectEffectFieldRefs(e.then, out);
      collectEffectFieldRefs(e.else, out);
    } else if (e.kind === "FOREACH") collectEffectFieldRefs(e.body, out);
  }
  return out;
}
const effectFieldRefs = computed(() => collectEffectFieldRefs(parseJson(selectedType.value?.effects, [])));

// 字段显示名（取首个含该 fieldKey 的产业字段中文名，汇总去重场景下同名 key 语义一致）。
function fieldNameOf(fieldKey: string): string {
  for (const it of industryTypes.value) {
    const f = (it.fields || []).find((x: any) => x.fieldKey === fieldKey);
    if (f) return f.name || f.label || fieldKey;
  }
  return fieldKey;
}
function partyLabel(role: string): string {
  const roles = parseJson(selectedType.value?.partyRoles, []);
  const p = roles.find((x: any) => x.role === role);
  return p?.label || role;
}

// 已选参与方公司、但其所属产业缺少效果所需字段 → 触发「该产业不支持该合同」。
const missingEffectFields = computed(() => {
  const out: {
    party: string;
    fieldKey: string;
    companyName: string;
    fieldName: string;
  }[] = [];
  for (const ref of effectFieldRefs.value) {
    if (!ref.party || !ref.fieldKey) continue;
    const companyId = (createForm.parties as Record<string, number>)[ref.party];
    if (companyId == null) continue; // 该参与方尚未选公司，暂不判定
    const industryTypeId = companyIndustryMap.value[companyId];
    const set = industryTypeId != null ? industryFieldKeyMap.value.get(industryTypeId) : undefined;
    if (!set || !set.has(ref.fieldKey)) {
      out.push({
        party: ref.party,
        fieldKey: ref.fieldKey,
        companyName: companyName(companyId) || `公司#${companyId}`,
        fieldName: fieldNameOf(ref.fieldKey),
      });
    }
  }
  return out;
});
// 参与方角色 → 当前所绑公司的产业类型 id（未绑定返回 undefined，交由求值器 fail-open）。
function getPartyIndustry(role?: string): number | null | undefined {
  if (!role) return undefined;
  const cid = (createForm.parties as Record<string, number>)[role];
  if (cid == null) return undefined;
  return companyIndustryMap.value[cid] ?? undefined;
}
// 输入项是否可见：无 branch → 始终可见；有 branch → 按 IF 条件实时求值显隐（fail-open 显示）。
function isFieldVisible(field: any): boolean {
  const b = field?.branch;
  if (!b || !b.cond) return true;
  const ctx: FormConditionCtx = {
    inputs: createForm.inputs,
    industryTypeOf: getPartyIndustry,
  };
  const res = evalFormCondition(b.cond, ctx);
  if (res === null) return true; // 无法判定 → 显示，避免误隐藏
  return b.when === "then" ? res : !res;
}

// 数据实体下拉选项（按当前比赛加载）
const entityEndpoint: Record<string, string> = {
  MATERIAL: "/materials",
  PART: "/parts",
  PRODUCT: "/products",
  WAREHOUSE: "/warehouses",
  PRODUCTION_LINE: "/production-lines",
  TECH_NODE: "/tech-nodes",
  FUEL: "/fuels",
  VEHICLE: "/vehicles",
  MAP_NODE: "/map-nodes",
  INFRASTRUCTURE: "/infrastructures",
};
// 存全量实体对象（含 origin 等字段），用于按所在地过滤原料。
const entityOptionsMap = reactive<Record<string, any[]>>({});
const entityLoading = reactive<Record<string, boolean>>({});

async function loadEntityOptions(entityType: string) {
  if (!entityType || entityOptionsMap[entityType] || entityLoading[entityType]) return;
  if (!compStore.competitionId) return;
  const ep = entityEndpoint[entityType];
  if (!ep) return;
  entityLoading[entityType] = true;
  try {
    const res = await api.get(ep, {
      params: { competitionId: compStore.competitionId, pageSize: 500 },
    });
    const list: any[] = Array.isArray(res) ? res : res.items || [];
    entityOptionsMap[entityType] = list;
  } catch (e) {
    console.error(e);
  } finally {
    entityLoading[entityType] = false;
  }
}
function entityOptions(entityType: string) {
  return entityOptionsMap[entityType] || [];
}

// 解析原料产地（JSON 字符串数组，节点名列表）
function parseOrigin(raw: any): string[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  try {
    const v = JSON.parse(raw);
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

// 公司字段值统一以 JSON 编码存储（字符串/数字/对象一律 JSON.stringify）。
// 所在地（location）为 STRING 类型，读回时原值是「节点名的 JSON 字符串」（如 "北京" 存为 "\"北京\""）。
// 必须解析回普通字符串再与原料 origin 的节点名比较，否则带引号的原值（"北京"）永远匹配不上，
// 导致「原料清单按参与方所在地过滤」时下拉全部落空、完全不显示原料。
function parseFieldStringValue(raw: any): string | null {
  if (raw == null) return null;
  if (typeof raw !== "string") return String(raw);
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed === "string") return parsed;
  } catch {
    /* 非 JSON，原样返回 */
  }
  return raw;
}

// 公司「所在地」节点名缓存：companyId -> 节点名（或 null 表示未设置/获取失败/未绑定）
const companyLocationCache = reactive<Record<number, string | null>>({});
const companyLocationLoading = reactive<Record<number, boolean>>({});
async function getCompanyLocation(companyId: number): Promise<string | null> {
  if (companyId == null) return null;
  if (companyLocationCache[companyId] !== undefined) return companyLocationCache[companyId];
  if (companyLocationLoading[companyId]) return null;
  companyLocationLoading[companyId] = true;
  try {
    const res: any = await companyFieldsApi.get(companyId);
    const fields: any[] = res?.fields || [];
    const loc = fields.find((f: any) => f.fieldKey === "location");
    companyLocationCache[companyId] = parseFieldStringValue(loc?.value ?? null);
    return companyLocationCache[companyId];
  } catch {
    companyLocationCache[companyId] = null;
    return null;
  } finally {
    companyLocationLoading[companyId] = false;
  }
}

// 原料清单输入项：根据所连参与方的所在地节点，过滤出「产地包含该节点」的原料。
// - 未连参与方 / 公司未绑定 / 所在地未设置：返回全部原料（避免阻断录入，仅提示）。
function materialOptionsForField(field: any): any[] {
  const all = entityOptions(field.entityType || "MATERIAL");
  const role = field.party;
  if (!role) return all;
  const companyId = (createForm.parties as Record<string, number>)[role];
  if (companyId == null) return all;
  const loc = companyLocationCache[companyId];
  if (loc === undefined || loc === null || loc === "") return all;
  return all.filter((m: any) => parseOrigin(m.origin).includes(loc));
}
// 按输入项类型解析对应实体类型（用于懒加载与列表选项）。
function entityTypeForFieldType(type: string): string {
  switch (type) {
    case "partList":
      return "PART";
    case "productList":
      return "PRODUCT";
    case "infrastructureList":
      return "INFRASTRUCTURE";
    case "fuelList":
      return "FUEL";
    case "vehicleList":
      return "VEHICLE";
    case "warehouseList":
      return "WAREHOUSE";
    default:
      return "MATERIAL";
  }
}
// 清单输入项的下拉选项（统一入口，避免模板内深层嵌套三元表达式引发 v-for 解析错误）。
function listOptions(field: any): any[] {
  if (field.type === "materialList") return materialOptionsForField(field);
  const all = entityOptions(field.entityType || entityTypeForFieldType(field.type));
  // 基建清单输入源若通过「基建列表」端口传入了受限基建名数组，仅展示这些基建；未传则展示全部。
  if (
    field.type === "infrastructureList" &&
    Array.isArray(field.allowedInfrastructures) &&
    field.allowedInfrastructures.length
  ) {
    const allowed = new Set(field.allowedInfrastructures.map(String));
    return all.filter((o: any) => allowed.has(o.name));
  }
  // 载具清单输入源若通过「载具列表」端口传入了受限载具名数组，仅展示这些载具；未传则展示全部。
  if (
    field.type === "vehicleList" &&
    Array.isArray(field.allowedVehicles) &&
    field.allowedVehicles.length
  ) {
    const allowed = new Set(field.allowedVehicles.map(String));
    return all.filter((o: any) => allowed.has(o.name));
  }
  return all;
}
// 基建清单输入源的过滤提示：返回 "仅显示「基建列表」限定的基建（N/总数）" 或 null。
function infraFilterHint(field: any): string | null {
  if (field.type !== "infrastructureList") return null;
  if (!Array.isArray(field.allowedInfrastructures) || !field.allowedInfrastructures.length)
    return null;
  const all = entityOptions(field.entityType || "INFRASTRUCTURE");
  const n = listOptions(field).length;
  return "仅显示「基建列表」限定的基建（" + n + "/" + all.length + "）";
}
// 载具清单输入源的过滤提示：返回 "仅显示「载具列表」限定的载具（N/总数）" 或 null。
function vehicleFilterHint(field: any): string | null {
  if (field.type !== "vehicleList") return null;
  if (!Array.isArray(field.allowedVehicles) || !field.allowedVehicles.length) return null;
  const all = entityOptions(field.entityType || "VEHICLE");
  const n = listOptions(field).length;
  return "仅显示「载具列表」限定的载具（" + n + "/" + all.length + "）";
}

// 当合同类型或参与方公司变化时，异步读取各原料清单所连参与方的所在地，触发下拉过滤。
function refreshMaterialLocationFilters() {
  const fields = inputSchemaFields.value.filter(
    (f: any) => f.type === "materialList" && f.party,
  );
  for (const f of fields) {
    const companyId = (createForm.parties as Record<string, number>)[f.party];
    if (companyId != null) getCompanyLocation(companyId);
  }
}
watch(
  () => [selectedType.value, createForm.parties],
  () => refreshMaterialLocationFilters(),
  { deep: true },
);

// ===== 地图节点（节点路径输入源） =====
const mapNodes = ref<any[]>([]);
const routeAddVal = ref<number | null>(null);
async function loadMapNodes() {
  if (mapNodes.value.length || !compStore.competitionId) return;
  try {
    let allNodes: any[] = [];
    let page = 1;
    while (true) {
      const res: any = await mapsApi.nodes.list(page, 200, compStore.competitionId);
      const items = Array.isArray(res) ? res : res?.items ?? [];
      allNodes = allNodes.concat(items);
      if (items.length < 200) break;
      page++;
    }
    mapNodes.value = allNodes;
  } catch (e) {
    console.error(e);
  }
}
function mapNodeName(id: number) {
  return mapNodes.value.find((m: any) => m.id === id)?.name || `#${id}`;
}
function routeLen(key: string) {
  return ((createForm.inputs[key] as any[]) || []).length;
}
function addableMapNodes(key: string) {
  const sel: number[] = (createForm.inputs[key] as any[]) || [];
  return mapNodes.value.filter((m: any) => !sel.includes(m.id));
}
function addRouteNode(key: string, id: number | null) {
  if (id == null) return;
  const arr: number[] = [...((createForm.inputs[key] as any[]) || [])];
  if (!arr.includes(id)) arr.push(id);
  createForm.inputs[key] = arr;
  routeAddVal.value = null;
}
// ===== 科技树节点（科技树清单输入源，单选） =====
const techNodes = ref<any[]>([]);
async function loadTechNodes() {
  if (techNodes.value.length || !compStore.competitionId) return;
  try {
    let allNodes: any[] = [];
    let page = 1;
    while (true) {
      const res: any = await api.get("/tech-nodes", { params: { page, pageSize: 200 } });
      const items = Array.isArray(res) ? res : res?.items ?? [];
      allNodes = allNodes.concat(items);
      if (items.length < 200) break;
      page++;
    }
    techNodes.value = allNodes;
  } catch (e) {
    console.error(e);
  }
}
function removeRouteNode(key: string, id: number) {
  createForm.inputs[key] = ((createForm.inputs[key] as any[]) || []).filter(
    (x: number) => x !== id,
  );
}
function moveRouteNode(key: string, idx: number, dir: number) {
  const arr: number[] = [...((createForm.inputs[key] as any[]) || [])];
  const j = idx + dir;
  if (j < 0 || j >= arr.length) return;
  const t = arr[idx];
  arr[idx] = arr[j];
  arr[j] = t;
  createForm.inputs[key] = arr;
}

// 工具函数
function parseJson(raw: any, fallback: any = []) {
  if (!raw) return fallback;
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw);
    } catch {
      return fallback;
    }
  }
  return raw;
}
function statusLabel(s: string) {
  return ({ DRAFT: "草稿", PENDING_EXEC: "待执行", EXECUTED: "已执行", TERMINATED: "已终止" } as any)[s] || s;
}
function statusType(s: string) {
  return ({ DRAFT: "info", PENDING_EXEC: "warning", EXECUTED: "success", TERMINATED: "danger" } as any)[s] || "info";
}
// fmtTime 统一引用 utils/format 的 formatTime（单一真源）
// 状态列悬停提示：草稿说明下一步，已执行/已终止展示执行时间
function statusHint(row: any): string {
  if (row.status === "DRAFT") return "草稿：填写完整参与方合同编号后可执行";
  if (row.status === "PENDING_EXEC") return "待执行：所有参与方编号已齐备，等待最后一方参与公司管理员执行";
  if (row.status === "EXECUTED") return `执行时间：${formatTime(row.executedAt)}`;
  if (row.status === "TERMINATED") return `执行时间：${formatTime(row.executedAt)}；已终止`;
  return "";
}
// 检查类型原始枚举 → 中文显示名（避免界面直接出现 VALUE_COMPARE 等原始 kind）
const COND_KIND_LABEL: Record<string, string> = {
  VALUE_COMPARE: "数值比较",
  FIELD_COMPARE: "字段比较",
  INDUSTRY_IS: "产业类型核对",
  ACCOUNT_COMPARE: "账户比较",
  INVENTORY_GTE: "库存下限",
  ASSET_OWNED: "资产持有",
  VEHICLE_COUNT: "载具数量",
  VEHICLE_LOCATION: "载具位置",
  TECH_COMPLETED: "科技完成",
  INFRA_ACTIVE: "基建启用",
};
function condKindLabel(s: string) {
  return COND_KIND_LABEL[s] || s;
}
function condKindFmt(_row: any, _col: any, val: any) {
  return condKindLabel(val || "");
}
function companyName(id: number) {
  return companies.value.find((c: any) => c.id === id)?.name;
}
function contractNumbersText(row: any) {
  const parties = parseJson(row?.parties, []);
  const nums = parties
    .filter((p: any) => !p.isHost)
    .map((p: any) => p.contractNumber)
    .filter((n: any) => n != null && String(n).trim() !== "");
  return nums.length ? nums.join("、") : "—";
}

const filteredContracts = computed(() => {
  if (!searchText.value) return contracts.value;
  const q = searchText.value.toLowerCase();
  return contracts.value.filter(
    (c: any) =>
      contractNumbersText(c).toLowerCase().includes(q) ||
      c.contractType?.name?.toLowerCase().includes(q),
  );
});

// 当前用户是否可操作合同（新建/执行/审核任一），用于空态引导展示
const canOperateContracts = computed(
  () => authStore.can("contract:manage") || authStore.canAny(["contract:execute", "contract:audit"]),
);
// 列表中是否存在草稿（决定「暂无草稿可执行」引导是否出现）
const hasDraft = computed(() => filteredContracts.value.some((c: any) => c.status === "DRAFT"));

// 执行按钮三态（与后端 execute() 的 assertAuditScope 保持一致）：
// - 无 execute/audit 权限 → 禁用（权限不足）
// - 非草稿 → 禁用（状态原因）
// - 仅持 audit（无 execute/manage）且合同参与方均不在 companyScopes 内 → 禁用（范围外，避免点击后被后端 403）
// 执行按钮状态（与后端 assertExecuteScope 对齐）：
// - 无 execute/audit 权限 → 禁用
// - 已执行/已终止 → 禁用（状态原因）
// - 草稿/待执行：落账前会签态，编号齐备由后端执行时统一校验；此处仅校验「执行方权限」
//   · 比赛级/超管（全局执行/管理）→ 直接可执行（兜底）
//   · 仅 audit 公司级管理员 → 必须是「最后一方参与公司」才可执行，否则禁用
function executeBtnState(row: any): { disabled: boolean; title: string } {
  if (!authStore.canAny(["contract:execute", "contract:audit"])) {
    return { disabled: true, title: "无合同执行权限" };
  }
  if (row.status === "EXECUTED" || row.status === "TERMINATED") {
    return {
      disabled: true,
      title:
        row.status === "EXECUTED"
          ? `合同已执行${row.executedAt ? `（${formatTime(row.executedAt)}）` : ""}，不可重复执行`
          : "合同已终止",
    };
  }
  const globalExec = authStore.can("contract:execute") || authStore.can("contract:manage");
  if (!globalExec) {
    // 仅 contract:audit 公司级管理员：必须是最后一个非主办方参与公司
    const parties = parseJson(row.parties, []);
    const real = parties.filter((p: any) => !p.isHost && typeof p.companyId === "number");
    const lastCo = real.length ? real[real.length - 1].companyId : null;
    if (lastCo == null || !authStore.canAuditCompany(lastCo)) {
      return { disabled: true, title: "仅合同最后一方参与公司的管理员可执行" };
    }
  }
  const tip =
    row.status === "PENDING_EXEC"
      ? "所有参与方编号已齐全，等待最后一方(乙方/丙方)执行落账"
      : "参与方编号齐备后可执行落账";
  return { disabled: false, title: tip };
}

const detailParties = computed(() => parseJson(detailRow.value?.parties, []));
const detailChecks = computed(() => {
  const r = parseJson(detailRow.value?.executionResult, null);
  return (r && r.checks) || [];
});
const precheckAllPass = computed(
  () => precheckResults.value.length > 0 && precheckResults.value.every((c) => c.passed),
);
const detailInputs = computed(() => {
  const inputs = parseJson(detailRow.value?.inputs, {});
  const schema = parseJson(detailRow.value?.contractType?.inputSchema, []);
  return schema.map((f: any) => ({
    key: f.key,
    label: f.label,
    type: f.type,
    entityType: f.entityType,
    value: inputs[f.key],
  }));
});
// 把执行日志解析为可读的「公司/字段/操作/前值→后值」表格，
// 让用户一眼看出合同执行到底改了哪些产业字段（避免"无声无变化"的困惑）。
const execLogRows = computed(() => {
  const arr = parseJson(detailRow.value?.executionLog, []);
  if (!Array.isArray(arr)) return [];
  return arr.map((e: any) => ({
    company: companyName(e.companyId) || `公司#${e.companyId}`,
    field: e.fieldName || e.fieldKey || "—",
    op: e.op || "—",
    before: fmtVal(e.before),
    after: fmtVal(e.after),
    value: fmtVal(e.value),
  }));
});
function fmtVal(v: any) {
  if (v == null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
function formatInputValue(row: any) {
  if (row.type === "materialList" || row.type === "partList" || row.type === "productList" || row.type === "infrastructureList" || row.type === "fuelList" || row.type === "vehicleList" || row.type === "warehouseList") {
    const obj = row.value && typeof row.value === "object" ? row.value : {};
    const entries = Object.entries(obj).map(([k, v]) => `${k}×${v}`);
    return entries.length ? entries.join("，") : "—";
  }
  if (row.type === "ENTITY") {
    const opt = entityOptions(row.entityType).find((o: any) => o.id === row.value);
    return opt ? `${opt.name} (id=${row.value})` : `实体id=${row.value}`;
  }
  if (row.type === "nodeRoute") {
    if (!mapNodes.value.length) loadMapNodes();
    const ids = Array.isArray(row.value) ? row.value : [];
    if (!ids.length) return "—";
    return ids.map((id: number) => mapNodeName(id)).join(" → ");
  }
  if (row.type === "mapNode") {
    return row.value ? String(row.value) : "—";
  }
  if (row.type === "techNode") {
    return row.value ? String(row.value) : "—";
  }
  return row.value;
}

async function loadContracts() {
  if (!compStore.competitionId) {
    contracts.value = [];
    return;
  }
  loading.value = true;
  try {
    const res = await contractsApi.list({ competitionId: compStore.competitionId });
    contracts.value = Array.isArray(res) ? res : res.items || [];
  } catch (e) {
    console.error(e);
  } finally {
    loading.value = false;
  }
}
async function loadTypes() {
  try {
    const res = await contractTypesApi.list(true);
    contractTypes.value = Array.isArray(res) ? res : res.items || [];
  } catch (e) {
    console.error(e);
  }
}
async function loadCompanies() {
  if (!compStore.competitionId) {
    companies.value = [];
    return;
  }
  try {
    const res = await api.get("/companies", {
      params: { competitionId: compStore.competitionId },
    });
    companies.value = Array.isArray(res) ? res : res.items || [];
  } catch (e) {
    console.error(e);
  }
}
async function loadIndustryTypes() {
  try {
    const res: any = await industryTypesApi.list();
    industryTypes.value = Array.isArray(res) ? res : res?.items || [];
  } catch (e) {
    console.error(e);
  }
}

function onTypeChange() {
  createForm.parties = {};
  createForm.inputs = {};
  inputSchemaFields.value.forEach((f: any) => {
    if (f.type === "ENTITY") loadEntityOptions(f.entityType);
    else if (f.type === "nodeRoute") {
      loadMapNodes();
      createForm.inputs[f.key] = Array.isArray(f.default) ? f.default : [];
    }     else if (f.type === "mapNode") {
      loadMapNodes();
    }     else if (f.type === "list")
      createForm.inputs[f.key] = Array.isArray(f.default) ? f.default : [];
    else if (f.type === "dict")
      createForm.inputs[f.key] =
        f.default && typeof f.default === "object" && !Array.isArray(f.default) ? f.default : {};
    else if (
      f.type === "materialList" ||
      f.type === "partList" ||
      f.type === "productList" ||
      f.type === "infrastructureList" ||
      f.type === "fuelList" ||
      f.type === "vehicleList" ||
      f.type === "warehouseList"
    ) {
      loadEntityOptions(f.entityType || entityTypeForFieldType(f.type));
      createForm.inputs[f.key] = {};
    }
  });
}

function addListItem(key: string, elementType?: string) {
  const arr = (createForm.inputs[key] as any[]) || (createForm.inputs[key] = []);
  arr.push(elementType === "number" ? 0 : "");
}
function removeListItem(key: string, i: number) {
  (createForm.inputs[key] as any[]).splice(i, 1);
}
function addDictEntry(key: string) {
  const obj = (createForm.inputs[key] as any) || (createForm.inputs[key] = {});
  let nk = "key" + (Object.keys(obj).length + 1);
  while (nk in obj) nk = nk + "_";
  obj[nk] = "";
}
function removeDictEntry(key: string, k: string) {
  delete (createForm.inputs[key] as any)[k];
}
function renameDictKey(key: string, oldK: string, newK: string) {
  const obj = createForm.inputs[key] as any;
  if (!obj || !(oldK in obj) || !newK || newK === oldK || newK in obj) return;
  const val = obj[oldK];
  delete obj[oldK];
  obj[newK] = val;
}

// ===== 原料清单（materialList）：多选原料 + 各自数量 → {"原料名": 数量} 字典 =====
function materialKeys(key: string): string[] {
  const obj = createForm.inputs[key] as Record<string, any> | undefined;
  return obj ? Object.keys(obj) : [];
}
function onMaterialSelect(key: string, names: string[]) {
  const obj = (createForm.inputs[key] as Record<string, any>) || (createForm.inputs[key] = {});
  // 保留已选原料的数量，新选补 0，取消的移除
  const next: Record<string, any> = {};
  for (const n of names) next[n] = n in obj ? obj[n] : 0;
  createForm.inputs[key] = next;
}
function removeMaterial(key: string, name: string) {
  const obj = createForm.inputs[key] as Record<string, any>;
  if (obj) delete obj[name];
}
function onMaterialSelectChange(key: string, names: any) {
  onMaterialSelect(key, Array.isArray(names) ? (names as string[]) : []);
}

function openCreate() {
  if (!compStore.competitionId) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  if (!authStore.can("contract:manage")) {
    ElMessage.warning("仅超级管理员可创建合同");
    return;
  }
  createForm.contractTypeId = undefined;
  createForm.parties = {};
  createForm.inputs = {};
  for (const k of Object.keys(partyNumbers)) delete partyNumbers[k];
  loadIndustryTypes();
  showCreate.value = true;
}

async function handleCreate() {
  if (!createForm.contractTypeId) {
    ElMessage.warning("请选择合同类型");
    return;
  }
  // 仅校验每方都选定了公司；合同编号允许留空（分步补全：发起方填自己那方，其余待补）
  for (const p of partyRolesSelectable.value) {
    if (!createForm.parties[p.role]) {
      ElMessage.warning(`请为「${p.label}」选择公司`);
      return;
    }
  }
  // 所选公司产业缺少效果字段 → 该产业不支持该合同，阻止创建。
  if (missingEffectFields.value.length) {
    showUnsupported.value = true;
    return;
  }
  const roles = parseJson(selectedType.value?.partyRoles, []);
  const partiesArr = roles.map((p: any) => ({
    role: p.role,
    companyId: p.isHost ? null : (createForm.parties[p.role] ?? null),
    isHost: !!p.isHost,
    // 发起方仅填自己管理的那一方；未填的编号留空（null），后续由各公司管理员在详情页补全
    contractNumber: p.isHost ? null : (partyNumbers[p.role] ? String(partyNumbers[p.role]).trim() : null),
  }));
  submitting.value = true;
  try {
    // 仅提交可见输入项（挂在 IF 分支下且当前条件不满足的字段不提交，避免误带值）。
    const inputsToSubmit: Record<string, any> = {};
    for (const f of inputSchemaFields.value) {
      if (isFieldVisible(f)) inputsToSubmit[f.key] = createForm.inputs[f.key];
    }
    // 后端：仅建草稿（DRAFT），不执行；编号可分步补全后再执行
    await contractsApi.create({
      competitionId: compStore.competitionId,
      contractTypeId: createForm.contractTypeId,
      parties: partiesArr,
      inputs: inputsToSubmit,
    });
    ElMessage.success("合同已创建（草稿），请在详情页补全其余各方编号后执行");
    showCreate.value = false;
    loadContracts();
  } catch (e: any) {
    showExecuteError(e);
  } finally {
    submitting.value = false;
  }
}

function openDetail(row: any) {
  detailRow.value = row;
  const schema = parseJson(row?.contractType?.inputSchema, []);
  schema.forEach((f: any) => {
    if (f.type === "ENTITY") loadEntityOptions(f.entityType);
  });
  editingNumber.role = null;
  showDetail.value = true;
  // 用列表行即时展示，并后台重新拉取完整合同（findOne 必带回 contractType/inputs/parties），
  // 避免本地缓存或列表副本缺字段导致「参与方 / 输入参数」显示不全。
  contractsApi
    .get(row.id)
    .then((fresh: any) => {
      if (detailRow.value && detailRow.value.id === fresh.id) detailRow.value = fresh;
    })
    .catch((e) => console.error(e));
}

// 该参与方编号是否可由当前用户编辑（权限隔离）：
// - 主办方不可编辑；已执行合同不可编辑。
// - 拥有 contract:manage / contract:execute（不受公司限制）→ 可编辑任意方；
// - 仅 contract:audit → 仅其 companyScopes 范围内公司的参与方可编辑。
function canEditParty(row: any): boolean {
  if (row.isHost) return false;
  if (detailRow.value?.status !== "DRAFT") return false;
  const u = authStore.user;
  if (!u) return false;
  const perms: string[] = u.permissions || [];
  const isSuper = u.role === "SUPER_ADMIN";
  const canManage = isSuper || perms.includes("contract:manage");
  const canExecute = isSuper || perms.includes("contract:execute");
  const canAudit = perms.includes("contract:audit");
  if (canManage || canExecute) return true;
  if (canAudit) {
    const scopes: number[] = u.companyScopes || [];
    return scopes.includes(row.companyId);
  }
  return false;
}

function startEditNumber(row: any) {
  editingNumber.role = row.role;
  editingNumber.value = row.contractNumber || "";
}
function cancelEditNumber() {
  editingNumber.role = null;
  editingNumber.value = "";
}
async function saveNumber(row: any) {
  const value = (editingNumber.value || "").trim();
  submitting.value = true;
  try {
    await contractsApi.updatePartyNumbers(detailRow.value.id, { [row.role]: value });
    const updated = await contractsApi.get(detailRow.value.id);
    detailRow.value = updated;
    cancelEditNumber();
    ElMessage.success("编号已保存");
    loadContracts();
  } catch (e: any) {
    showExecuteError(e);
  } finally {
    submitting.value = false;
  }
}

// 列表「执行」：所有非主办方编号齐全后落账；不齐则后端报错提示具体角色
async function executeContract(row: any) {
  if (!authStore.canAny(["contract:execute", "contract:audit"])) {
    ElMessage.warning("无权执行合同");
    return;
  }
  if (row.status !== "DRAFT") {
    ElMessage.warning("仅草稿状态可执行");
    return;
  }
  submitting.value = true;
  try {
    await contractsApi.execute(row.id);
    ElMessage.success("合同已执行");
    loadContracts();
  } catch (e: any) {
    showExecuteError(e);
  } finally {
    submitting.value = false;
  }
}

// 执行/创建失败时弹出错误窗口，展示后端返回的具体错误信息
function showExecuteError(e: any) {
  const msg: string =
    e?.response?.data?.message || (e?.message ? String(e.message) : "操作失败");
  ElMessageBox.alert(msg, "合同操作失败", {
    type: "error",
    confirmButtonText: "我知道了",
  }).catch(() => {});
}
async function handleDelete(row: any) {
  await ElMessageBox.confirm(`确定删除合同「${row.name}」吗？`, "删除确认", {
    type: "warning",
    confirmButtonText: "下一步",
    cancelButtonText: "取消",
  });
  await ElMessageBox.confirm(
    `此操作不可恢复，将彻底删除合同「${row.name}」及其关联数据，确认继续？`,
    "二次确认",
    {
      type: "error",
      confirmButtonText: "确认删除",
      cancelButtonText: "再想想",
      distinguishCancelAndClose: true,
    },
  );
  try {
    await contractsApi.remove(row.id);
    ElMessage.success("已删除");
    loadContracts();
  } catch (e) {
    console.error(e);
  }
}

function handleContractChanged(payload: any) {
  // 强时效：其他前端（含管理员）执行合同后，本页即刻刷新列表
  if (payload?.competitionId && payload.competitionId === compStore.competitionId) {
    loadContracts();
  }
}

onMounted(() => {
  // 类型 / 公司列表仅用于「新建合同」表单；无对应读权限的账号（如仅 contract:view）
  // 不会进新建流程，故按权限懒加载，避免无谓的 403 弹「权限不足」提示。
  if (authStore.can("contractType:view")) loadTypes();
  if (authStore.can("company:view")) loadCompanies();
  if (authStore.can("industryType:view")) loadIndustryTypes();
  loadContracts();
  // 实时同步：监听合同状态变更广播，管理员或其他端操作后本页即刻刷新
  onRealtime("contract:changed", handleContractChanged);
});

// 选择公司参与方后自动校验：效果字段在所选公司产业中缺失时弹出「该产业不支持该合同」；
// 改选到满足字段的公司后自动关闭。
watch(
  () => createForm.parties,
  () => {
    showUnsupported.value = missingEffectFields.value.length > 0;
  },
  { deep: true },
);

// 切换比赛时先清空旧数据再重新拉取，避免停留在上一个比赛的旧数据。
useCompetitionReload(
  () => {
    if (authStore.can("contractType:view")) loadTypes();
    if (authStore.can("company:view")) loadCompanies();
    if (authStore.can("industryType:view")) loadIndustryTypes();
    loadContracts();
  },
  () => {
    contracts.value = [];
    contractTypes.value = [];
    companies.value = [];
    industryTypes.value = [];
  },
);

useResourceChanged("contracts", () => {
  loadContracts();
});

onUnmounted(() => {
  offRealtime("contract:changed", handleContractChanged);
});
</script>

<style scoped>
.mm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.mm-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.mm-actions {
  display: flex;
  gap: 8px;
}
.party-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.party-boxes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.party-box {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  padding: 2px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #f4f6fb;
  color: #303133;
  font-size: 13px;
  line-height: 20px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.party-box--host {
  border-color: #e6c07b;
  background: var(--color-warning-soft);
  color: #b8821a;
}
.num-empty {
  color: #e6a23c;
  font-style: italic;
}
.host-hint {
  color: #909399;
  font-size: 13px;
}
.list-editor {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.list-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.list-row .el-input,
.list-row .el-input-number {
  flex: 1;
}
.route-editor {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.material-editor {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.dashed-box {
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  padding: 8px;
  width: 100%;
}
.material-editor .el-select {
  width: 100%;
}
.material-qty {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.loc-hint {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}
.material-qty-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.material-name {
  flex: 1;
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.route-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.route-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #ecf5ff;
  border: 1px solid #b3d8ff;
  border-radius: 14px;
  padding: 2px 8px;
  font-size: 12px;
  color: #303133;
}
.route-idx {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #409eff;
  color: #fff;
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.route-name {
  flex: 1;
}
.route-ops {
  display: inline-flex;
  gap: 2px;
}
.no-comp-warning {
  text-align: center;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--color-warning-soft);
  border: 1px solid rgba(var(--color-warning-soft-rgb), 0.3);
  border-radius: 6px;
  color: #b45309;
  font-size: 13px;
}
.json-box {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
