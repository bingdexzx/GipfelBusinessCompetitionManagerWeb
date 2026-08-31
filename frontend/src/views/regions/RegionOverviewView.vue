<template>
  <div class="region-overview">
    <h2 class="page-title">区域总览</h2>

    <div v-if="!compStore.competitionId" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <template v-else>
      <el-empty v-if="regions.length === 0 && !loading" description="地图中暂无区域，请在地图管理中为节点设置所属区域" />
      <div v-else-if="loading" class="ro-loading">正在加载区域数据…</div>

      <div v-for="region in regions" :key="region.region" class="region-band">
        <div class="band-header">
          <div class="band-title">
            <span class="band-name">{{ region.region }}</span>
          </div>
        </div>

        <!-- 上半部分：消费者需求 + 上半区数据框 -->
        <div class="band-section">
          <div class="section-head">
            <span class="section-title">消费者需求</span>
            <div class="section-actions">
              <el-button v-if="canEdit" size="small" type="success" plain @click="openAddDemand(region)">
                + 添加需求
              </el-button>
              <el-button v-if="canEdit" size="small" type="primary" plain @click="openAddFrame(region, 'top')">
                + 添加数据框
              </el-button>
            </div>
          </div>

          <div v-if="demandsOf(region).length === 0 && topCards(region).length === 0" class="band-empty">暂无需求与数据</div>

          <div class="band-frames">
            <div v-for="d in demandsOf(region)" :key="d.id" class="frame demand-frame">
              <div class="frame-top">
                <span class="frame-name" :title="d.productType">{{ d.productType }}</span>
                <div v-if="canEdit" class="frame-actions">
                  <el-icon class="fa-edit" title="编辑" @click="openEditDemand(region, d)"><Edit /></el-icon>
                  <el-icon class="fa-del" title="删除" @click="removeDemand(region, d)"><Close /></el-icon>
                </div>
              </div>
              <div class="frame-value">
                {{ d.quantity }}<span class="frame-unit"> 件</span>
              </div>
              <div class="frame-meta" v-if="d.note">备注：{{ d.note }}</div>
            </div>
            <div v-for="card in topCards(region)" :key="card.id" class="frame" :class="{ invalid: !card.valid }">
              <div class="frame-top">
                <span class="frame-name" :title="card.displayName">{{ card.displayName }}</span>
                <div v-if="canEdit" class="frame-actions">
                  <el-icon class="fa-edit" title="编辑" @click="openEditFrame(region, card)"><Edit /></el-icon>
                  <el-icon class="fa-del" title="移除" @click="removeFrame(region, card)"><Close /></el-icon>
                </div>
              </div>
              <div class="frame-value">{{ formatValue(card) }}</div>
              <div class="frame-meta" v-if="!card.valid">字段已失效</div>
            </div>
          </div>
        </div>

        <!-- 下半部分：区域数据（数据框，下方） -->
        <div class="band-section">
          <div class="section-head">
            <span class="section-title">区域数据</span>
            <el-button v-if="canEdit" size="small" type="primary" plain @click="openAddFrame(region, 'bottom')">
              + 添加数据框
            </el-button>
          </div>

          <div v-if="bottomCards(region).length === 0" class="band-empty">暂无数据</div>

          <div class="band-frames">
            <div v-for="card in bottomCards(region)" :key="card.id" class="frame" :class="{ invalid: !card.valid }">
              <div class="frame-top">
                <span class="frame-name" :title="card.displayName">{{ card.displayName }}</span>
                <div v-if="canEdit" class="frame-actions">
                  <el-icon class="fa-edit" title="编辑" @click="openEditFrame(region, card)"><Edit /></el-icon>
                  <el-icon class="fa-del" title="移除" @click="removeFrame(region, card)"><Close /></el-icon>
                </div>
              </div>
              <div class="frame-value">{{ formatValue(card) }}</div>
              <div class="frame-meta" v-if="!card.valid">字段已失效</div>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 添加 / 编辑数据框 -->
    <el-dialog append-to-body v-model="showFrame" :title="editingCard ? '编辑数据框' : '添加数据框'" width="480px">
      <el-form label-width="92px">
        <el-form-item label="数据来源公司" required>
          <el-select
            v-model="frameCompanyId"
            placeholder="选择本区域内的公司"
            filterable
            style="width: 100%"
            :disabled="!!editingCard"
            @change="onCompanyChange"
          >
            <el-option
              v-for="c in regionCompanies"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="产业字段" required>
          <el-select
            v-model="frameFieldId"
            placeholder="选择该公司的一个产业字段"
            style="width: 100%"
            :disabled="!frameCompanyId"
            @change="onFieldChange"
          >
            <el-option
              v-for="f in companyFields"
              :key="f.id"
              :label="`${f.name}（${fieldTypeLabel(f.fieldType)}${f.visible === false ? '·隐藏' : ''}）`"
              :value="f.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="展示名称" required>
          <el-input v-model="frameDisplayName" placeholder="如：本月产量 / 现金余额" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showFrame = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveFrame">保存</el-button>
      </template>
    </el-dialog>

    <!-- 添加 / 编辑消费者需求 -->
    <el-dialog append-to-body v-model="showDemand" :title="editingDemand ? '编辑需求' : '添加需求'" width="480px">
      <el-form label-width="92px">
        <el-form-item label="产品" required>
          <el-select
            v-model="demandForm.productId"
            placeholder="选择产品"
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="p in productOptions"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="产品数量" required>
          <el-input-number v-model="demandForm.quantity" :min="0" :step="1" controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="demandForm.note" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDemand = false">取消</el-button>
        <el-button type="success" :loading="savingDemand" @click="saveDemand">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Edit, Close } from "@element-plus/icons-vue";
import { useCompetitionStore } from "@/stores/competition";
import { useAuthStore } from "@/stores/auth";
import { regionsApi, companyFieldsApi, consumerDemandsApi, productsApi } from "@/api/index";
import { useResourceChanged } from "@/realtime/useResourceChanged";

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const canEdit = computed(() => authStore.can("data:region:edit"));

const regions = ref<any[]>([]);
const demands = ref<any[]>([]);
const loading = ref(false);

// 产品下拉选项（来自产品库，关联真实产品）
const productOptions = ref<{ id: number; name: string }[]>([]);

function demandsOf(region: any): any[] {
  return (demands.value || []).filter((d: any) => d.region === region.region);
}

// ===== 数据框编辑对话框 =====
const showFrame = ref(false);
const frameZone = ref<"top" | "bottom">("bottom");
const saving = ref(false);
const activeRegion = ref<any>(null);
const editingCard = ref<any>(null);
const regionCompanies = ref<any[]>([]);
const companyFields = ref<any[]>([]);
const frameCompanyId = ref<number | null>(null);
const frameFieldId = ref<number | null>(null);
const frameDisplayName = ref("");

// ===== 消费者需求编辑对话框 =====
const showDemand = ref(false);
const savingDemand = ref(false);
const editingDemand = ref<any>(null);
const demandForm = ref<{ productId: number | null; quantity: number; note: string }>({
  productId: null,
  quantity: 0,
  note: "",
});

const fieldTypeLabel = (t: string) =>
  ({ STRING: "文本", NUMBER: "数值", BOOLEAN: "布尔", DICTIONARY: "字典", LIST: "列表" } as any)[t] ||
  t;

async function loadRegions() {
  if (!compStore.competitionId) {
    regions.value = [];
    return;
  }
  loading.value = true;
  try {
    const list = (await regionsApi.mapOverview(compStore.competitionId)) || [];
    regions.value = (list as any[]).map((r: any) => ({ ...r, loading: false }));
  } catch (e) {
    console.error("Failed to load map regions:", e);
  } finally {
    loading.value = false;
  }
}

async function loadDemands() {
  if (!compStore.competitionId) {
    demands.value = [];
    return;
  }
  try {
    const list = (await consumerDemandsApi.list(compStore.competitionId)) || [];
    demands.value = list as any[];
  } catch (e) {
    console.error("Failed to load consumer demands:", e);
  }
}

async function loadProducts() {
  try {
    const res: any = (await productsApi.list(1, 200)) || {};
    // 后端列表接口返回分页对象 {items,total,...} 或直接数组，做兼容
    const list: any[] = Array.isArray(res) ? res : res.items || [];
    productOptions.value = list
      .map((p: any) => ({ id: p.id, name: p.name }))
      .filter((p: any) => p.id != null);
  } catch (e) {
    productOptions.value = [];
  }
}

// ===== 数据框 =====
function topCards(region: any): any[] {
  return (region.cards || []).filter((c: any) => c.zone === "top");
}
function bottomCards(region: any): any[] {
  return (region.cards || []).filter((c: any) => c.zone !== "top");
}

async function openAddFrame(region: any, zone: "top" | "bottom" = "bottom") {
  if (!compStore.competitionId) return;
  activeRegion.value = region;
  frameZone.value = zone;
  editingCard.value = null;
  frameCompanyId.value = null;
  frameFieldId.value = null;
  frameDisplayName.value = "";
  companyFields.value = [];
  // 本区「当地公司」直接来自地图区域总览返回，无需额外请求
  regionCompanies.value = region.companies || [];
  showFrame.value = true;
}

async function openEditFrame(region: any, card: any) {
  activeRegion.value = region;
  editingCard.value = card;
  frameZone.value = card.zone || "bottom";
  regionCompanies.value = region.companies || [];
  frameCompanyId.value = card.companyId;
  await onCompanyChange(card.companyId);
  frameFieldId.value = card.industryFieldId;
  frameDisplayName.value = card.displayName;
  showFrame.value = true;
}

async function onCompanyChange(companyId: number) {
  frameFieldId.value = null;
  frameDisplayName.value = "";
  if (!companyId) {
    companyFields.value = [];
    return;
  }
  try {
    const res = await companyFieldsApi.get(companyId, { includeHidden: true });
    // 区域总览字段选择展示全部字段（含 hidden）：隐藏字段只作用于公司管理界面不展示，
    // 区域总览仍可将其选中并发布到数据框（发布后照常展示）。
    companyFields.value = res?.fields || [];
  } catch (e) {
    companyFields.value = [];
  }
}

function onFieldChange(fieldId: number) {
  const f = companyFields.value.find((x) => x.id === fieldId);
  if (f && !editingCard.value) frameDisplayName.value = f.name;
}

async function saveFrame() {
  if (!activeRegion.value) return;
  if (!frameCompanyId.value || !frameFieldId.value || !frameDisplayName.value.trim()) {
    ElMessage.warning("请完整填写公司、产业字段与展示名称");
    return;
  }
  saving.value = true;
  try {
    const cards = activeRegion.value.cards || [];
    const newCard = {
      id:
        editingCard.value?.id ||
        `c-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      displayName: frameDisplayName.value.trim(),
      companyId: frameCompanyId.value,
      industryFieldId: frameFieldId.value,
      zone: frameZone.value,
    };
    let next: any[];
    if (editingCard.value) {
      next = cards.map((c: any) => (c.id === editingCard.value.id ? newCard : c));
    } else {
      next = [...cards, newCard];
    }
    await regionsApi.saveOverviewCardsByName(
      activeRegion.value.region,
      next,
      compStore.competitionId ?? undefined,
    );
    // 重新拉取该区域总览（实时值需服务端重算）
    await loadRegions();
    ElMessage.success("已保存");
    showFrame.value = false;
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  } finally {
    saving.value = false;
  }
}

async function removeFrame(region: any, card: any) {
  await ElMessageBox.confirm(`移除数据框「${card.displayName}」？`, { type: "warning" });
  try {
    const next = (region.cards || []).filter((c: any) => c.id !== card.id);
    await regionsApi.saveOverviewCardsByName(
      region.region,
      next,
      compStore.competitionId ?? undefined,
    );
    await loadRegions();
    ElMessage.success("已移除");
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

// ===== 消费者需求 =====
function openAddDemand(region: any) {
  if (!compStore.competitionId) return;
  activeRegion.value = region;
  editingDemand.value = null;
  demandForm.value = { productId: null, quantity: 0, note: "" };
  showDemand.value = true;
}

function openEditDemand(region: any, d: any) {
  activeRegion.value = region;
  editingDemand.value = d;
  demandForm.value = {
    productId: d.productId ?? null,
    quantity: d.quantity ?? 0,
    note: d.note || "",
  };
  showDemand.value = true;
}

async function saveDemand() {
  if (!activeRegion.value) return;
  if (demandForm.value.productId == null) {
    ElMessage.warning("请选择产品");
    return;
  }
  savingDemand.value = true;
  try {
    const payload = {
      region: activeRegion.value.region,
      productId: demandForm.value.productId as number,
      quantity: demandForm.value.quantity ?? 0,
      // 始终携带 note 字段：清空备注时传空字符串而非 undefined，
      // 否则 axios 会丢弃 undefined 字段，导致后端 update 不清除备注（#备注无法删除）。
      note: (demandForm.value.note ?? "").trim(),
    };
    if (editingDemand.value) {
      await consumerDemandsApi.update(editingDemand.value.id, payload);
    } else {
      await consumerDemandsApi.create({
        competitionId: compStore.competitionId ?? undefined,
        ...payload,
      });
    }
    await loadDemands();
    ElMessage.success("已保存");
    showDemand.value = false;
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  } finally {
    savingDemand.value = false;
  }
}

async function removeDemand(region: any, d: any) {
  await ElMessageBox.confirm(`删除需求「${d.productType}（${d.quantity} 件）」？`, {
    type: "warning",
  });
  try {
    await consumerDemandsApi.remove(d.id, compStore.competitionId ?? undefined);
    await loadDemands();
    ElMessage.success("已删除");
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

function formatValue(card: any) {
  if (!card.valid) return "字段已失效";
  const v = card.value;
  if (v == null || v === "") return "—";
  if (card.fieldType === "BOOLEAN") return v === "true" ? "是" : "否";
  if (card.fieldType === "NUMBER") return String(v);
  if (card.fieldType === "DICTIONARY" || card.fieldType === "LIST") {
    try {
      return JSON.stringify(JSON.parse(v));
    } catch {
      return String(v);
    }
  }
  return String(v);
}

onMounted(async () => {
  await Promise.all([loadRegions(), loadDemands(), loadProducts()]);
});

// 切换比赛时重新拉取：先清空本地数据，等网络确认后再渲染，避免停留在上一个比赛的旧数据（错误内容）。
watch(
  () => compStore.competitionId,
  (newId, oldId) => {
    if (newId && newId !== oldId) {
      regions.value = [];
      demands.value = [];
    }
    loadRegions();
    loadDemands();
  },
);
// 区域配置变更 / 地图节点区域变更 → 重新加载区域带
useResourceChanged("region", () => loadRegions());
useResourceChanged("map-nodes", () => loadRegions());
// 公司产业字段写入 / 合同执行改写字段 → 刷新各区域实时值
useResourceChanged("company-field", () => loadRegions());
// 需求变更 → 重新加载需求列表
useResourceChanged("consumer-demand", () => loadDemands());
</script>

<style scoped>
.region-overview {
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text-primary, #1f1f1f);
  margin: 0 0 16px;
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

.region-band {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.band-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.band-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.band-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

/* 大框内的两个分区：上=消费者需求，下=区域数据 */
.band-section {
  padding: 12px 0;
  border-top: 1px dashed #eceef2;
}
.band-section:first-of-type {
  border-top: none;
  padding-top: 0;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.section-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  letter-spacing: 0.5px;
}
.section-title::before {
  content: "";
  display: inline-block;
  width: 3px;
  height: 12px;
  background: #c0c4cc;
  border-radius: 2px;
  margin-right: 7px;
  vertical-align: -1px;
}
.band-empty {
  font-size: 13px;
  color: #c0c4cc;
  padding: 16px 4px;
}
.ro-loading {
  text-align: center;
  padding: 40px 0;
  color: #909399;
  font-size: 13px;
}
.band-frames {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

/* 区域数据框（蓝） */
.frame {
  min-width: 180px;
  flex: 0 0 auto;
  background: linear-gradient(180deg, #f7f9ff 0%, #eef3ff 100%);
  border: 1px solid #d6e2ff;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.frame.invalid {
  background: #fafafa;
  border-color: #e4e7ed;
}

/* 消费者需求框（绿，与数据框区分） */
.demand-frame {
  background: linear-gradient(180deg, #f0faf5 0%, #e6f7ef 100%);
  border-color: #c8ecd9;
}
.demand-frame .frame-value {
  color: #1a7f4f;
}
.demand-frame.invalid {
  background: #fafafa;
  border-color: #e4e7ed;
}

.frame-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.frame-name {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 130px;
}
.frame-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.fa-edit,
.fa-del {
  cursor: pointer;
  font-size: 14px;
  color: #909399;
}
.fa-edit:hover {
  color: #409eff;
}
.demand-frame .fa-edit:hover {
  color: #1a7f4f;
}
.fa-del:hover {
  color: #f56c6c;
}
.frame-value {
  font-size: 22px;
  font-weight: 700;
  color: #1f2d3d;
  line-height: 1.2;
  word-break: break-all;
}
.frame-unit {
  font-size: 13px;
  font-weight: 500;
  color: #909399;
}
.frame.invalid .frame-value {
  font-size: 14px;
  font-weight: 500;
  color: #c0c4cc;
}
.frame-meta {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
