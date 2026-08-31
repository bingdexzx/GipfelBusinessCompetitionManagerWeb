<template>
  <div class="comp-page">
    <!-- ========== 上半部分：比赛管理 ========== -->
    <div class="comp-section">
      <div class="pm-toolbar">
        <h2 class="pm-title">比赛管理</h2>
        <div class="pm-actions">
          <el-button v-if="isSuperAdmin" type="primary" @click="openCreate">+ 新建比赛</el-button>
        </div>
      </div>

      <el-table
        :key="tableKey"
        v-loading="loading"
        :data="competitions"
        row-key="id"
        :current-row-key="compStore.competitionId"
        border
        stripe
        style="width: 100%"
        highlight-current-row
      >
        <el-table-column prop="name" label="名称" />
        <el-table-column label="状态">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'danger'">{{
              row.status === "ACTIVE" ? "进行中" : "已关闭"
            }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前财年">
          <template #default="{ row }">{{ getCurrentFiscalYear(row) ?? "-" }}</template>
        </el-table-column>
        <el-table-column label="用户">
          <template #default="{ row }">{{ row._count?.users || 0 }}</template>
        </el-table-column>
        <el-table-column label="公司">
          <template #default="{ row }">{{ row._count?.companies || 0 }}</template>
        </el-table-column>
        <el-table-column label="操作" width="280" fixed="right">
          <template #default="{ row }">
            <template v-if="!isOwnedCompetition">
              <el-button
                size="small"
                :type="compStore.competitionId === row.id ? 'warning' : 'success'"
                @click.stop="selectCompetition(row)"
                >{{ compStore.competitionId === row.id ? "取消选择" : "选择" }}</el-button
              >
            </template>
            <el-tag v-else-if="compStore.competitionId === row.id" type="info" size="small"
              >已自动锁定</el-tag
            >
            <span v-else style="color: #c0c4cc; font-size: 12px">不可切换</span>
            <el-button v-if="isSuperAdmin" size="small" @click.stop="openEdit(row)">编辑</el-button>
            <el-button
              v-if="isSuperAdmin"
              size="small"
              :type="row.status === 'ACTIVE' ? 'warning' : 'success'"
              @click.stop="toggleStatus(row)"
              >{{ row.status === "ACTIVE" ? "关闭" : "开启" }}</el-button
            >
            <el-button
              v-if="isSuperAdmin"
              size="small"
              type="danger"
              @click.stop="handleDelete(row)"
              >删除</el-button
            >
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ========== 下半部分：财年管理 ========== -->
    <div class="comp-section" style="margin-top: 24px">
      <div class="pm-toolbar">
        <h2 class="pm-title">
          财年管理
          <span v-if="selectedComp" style="font-size: 14px; color: #8c8c8c">
            ：{{ selectedComp.name }}</span
          >
        </h2>
        <div v-if="selectedComp && isSuperAdmin" class="pm-actions">
          <el-button
            type="success"
            size="small"
            :disabled="hasActiveFiscalYear"
            @click="startNextFiscalYear"
            >开始新财年</el-button
          >
        </div>
      </div>

      <div v-if="!selectedComp" class="fy-empty">
        <el-icon :size="40" color="#C0C4CC"><Warning /></el-icon>
        <p>请先在上方选择一个比赛</p>
      </div>

      <el-table v-else :data="fiscalYears" border stripe size="small" style="width: 100%">
        <el-table-column label="财年">
          <template #default="{ row }">第 {{ row.year }} 财年</template>
        </el-table-column>
        <el-table-column label="状态">
          <template #default="{ row }">
            <el-tag :type="row.status === 'ACTIVE' ? 'success' : 'danger'" size="small">{{
              row.status === "ACTIVE" ? "进行中" : "已结束"
            }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开始时间">
          <template #default="{ row }">{{ $formatTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="更新时间">
          <template #default="{ row }">{{ $formatTime(row.updatedAt) }}</template>
        </el-table-column>
        <el-table-column v-if="isSuperAdmin" label="操作" width="120">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'ACTIVE'"
              size="small"
              type="warning"
              @click="endFiscalYear(row)"
              >结束财年</el-button
            >
            <span v-else style="color: #c0c4cc">已结束</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑比赛' : '新建比赛'"
      width="480px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="formRules"
        label-width="80px"
        @submit.prevent="handleSubmit"
      >
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch, onUnmounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Warning } from "@element-plus/icons-vue";
import api from "@/api/request";
import { useAuthStore } from "@/stores/auth";
import { useCompetitionStore } from "@/stores/competition";
import { onRealtime, offRealtime } from "@/realtime/socket";
import { useResourceChanged } from "@/realtime/useResourceChanged";

const authStore = useAuthStore();
const compStore = useCompetitionStore();
const isSuperAdmin = computed(() => authStore.can("competition:manage"));
// 归属比赛的账号（competitionId 非空）其比赛已被自动锁定，禁止在比赛管理页手动切换。
const isOwnedCompetition = computed(() => authStore.user?.competitionId != null);

const competitions = ref<any[]>([]);
const loading = ref(false);
const selectedComp = computed(() => compStore.selected);
const fiscalYears = ref<any[]>([]);
const tableKey = ref(0);
const dialogVisible = ref(false),
  isEdit = ref(false),
  editingId = ref(0);
const submitting = ref(false),
  formRef = ref();
const form = reactive({ name: "" });
const formRules = { name: [{ required: true, message: "请输入比赛名称", trigger: "blur" }] };
const hasActiveFiscalYear = computed(() =>
  fiscalYears.value.some((f: any) => f.status === "ACTIVE"),
);

onMounted(() => {
  refreshAll();
  // 实时同步：其他客户端（或本机其它标签页）增删/开关财年时，立即刷新当前比赛的财年列表
  onRealtime("fiscal-year:changed", handleFiscalYearRealtime);
});

useResourceChanged("competitions", () => {
  loadCompetitions();
}, { scope: "global" });

onUnmounted(() => offRealtime("fiscal-year:changed", handleFiscalYearRealtime));

// 财年列表始终跟随当前选中的比赛：切换比赛时重载、取消选择时清空（保证按比赛划分）
watch(
  () => compStore.competitionId,
  (id) => {
    if (id != null) loadFiscalYears(id);
    else fiscalYears.value = [];
  },
);

function handleFiscalYearRealtime(payload: any) {
  if (!payload?.competitionId || payload.competitionId !== compStore.competitionId) return;
  loadFiscalYears(payload.competitionId);
}
async function loadCompetitions() {
  loading.value = true;
  try {
    const res = await api.get("/competitions");
    // 防御性归一化：缓存层返回裸数组（服务端忽略分页、一次给全量），
    // 个别分支也可能返回分页对象 {items,...}，统一取数组避免 [...res] 对对象展开抛 TypeError。
    const arr = Array.isArray(res) ? res : (res?.items ?? []);
    competitions.value = [...arr];
    tableKey.value++;
  } catch (e) {
    console.error("Failed to load competitions:", e);
  } finally {
    loading.value = false;
  }
}

async function refreshAll() {
  await loadCompetitions();
  if (compStore.competitionId) await loadFiscalYears(compStore.competitionId);
}

function getCurrentFiscalYear(comp: any) {
  const fys = comp.fiscalYears;
  if (!fys?.length) return null;
  const active = fys.find((f: any) => f.status === "ACTIVE");
  return active ? `第 ${active.year} 财年` : null;
}

async function selectCompetition(row: any) {
  if (compStore.competitionId === row.id) {
    compStore.clearSelection();
    fiscalYears.value = [];
    ElMessage.info("已取消选择");
    return;
  }
  compStore.selectCompetition(row);
  ElMessage.success(`已选择: ${row.name}`);
  await loadFiscalYears(row.id);
}

async function loadFiscalYears(compId: number) {
  try {
    const res = await api.get(`/competitions/${compId}/fiscal-years`);
    fiscalYears.value = [...(res || [])];
  } catch (e) {
    console.error("Failed to load fiscal years:", e);
  }
}

function openCreate() {
  isEdit.value = false;
  form.name = "";
  dialogVisible.value = true;
}
function openEdit(row: any) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name;
  dialogVisible.value = true;
}
function resetForm() {
  formRef.value?.resetFields();
}

async function handleSubmit() {
  await formRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    submitting.value = true;
    try {
      if (isEdit.value) {
        await api.patch(`/competitions/${editingId.value}`, form);
        ElMessage.success("已更新");
      } else {
        await api.post("/competitions", form);
        ElMessage.success("已创建");
      }
      dialogVisible.value = false;
      refreshAll();
    } catch (e) {
      console.error("Failed to submit competition:", e);
    } finally {
      submitting.value = false;
    }
  });
}

async function toggleStatus(row: any) {
  const ns = row.status === "ACTIVE" ? "CLOSED" : "ACTIVE";
  await ElMessageBox.confirm(`确定${ns === "ACTIVE" ? "开启" : "关闭"}？`, { type: "warning" });
  try {
    await api.patch(`/competitions/${row.id}`, { status: ns });
    ElMessage.success("已更新");
    refreshAll();
  } catch (e) {
    console.error("Failed to toggle competition status:", e);
  }
}

async function handleDelete(row: any) {
  await ElMessageBox.confirm(`确定删除"${row.name}"？该比赛下的所有数据将被永久删除`, {
    type: "warning",
    confirmButtonText: "确认删除",
  });
  await ElMessageBox.confirm(`再次确认：删除"${row.name}"后数据不可恢复，继续吗？`, {
    type: "error",
    confirmButtonText: "最终确认",
  });
  await ElMessageBox.confirm(`最后一次确认：真的要删除"${row.name}"吗？`, {
    type: "error",
    confirmButtonText: "我确定",
  });
  try {
    await api.delete(`/competitions/${row.id}`);
    // 删除的是当前选中的比赛时，立即清空顶部栏的比赛/财年标识
    // 使用宽松比较，规避 selected.id 与 row.id 因类型（number/string）或引用不一致导致判定失败
    if (selectedComp.value && String(selectedComp.value.id) === String(row.id)) {
      fiscalYears.value = [];
      compStore.clearSelection();
    }
    ElMessage.success("已删除");
    await refreshAll();
    // 保险：刷新后若当前选中的比赛已被删除（悬空引用），再次同步清空顶部栏
    if (
      compStore.selected &&
      !competitions.value.some((c) => String(c.id) === String(compStore.selected?.id))
    ) {
      compStore.clearSelection();
    }
  } catch (e) {
    console.error("Failed to delete competition:", e);
  }
}

async function startNextFiscalYear() {
  if (!selectedComp.value) return;
  // 按当前列表的实际年份推算下一个财年（取最大年份 +1），避免依赖 length 在列表陈旧时算出重复年份
  const maxYear = fiscalYears.value.reduce(
    (m: number, f: any) => Math.max(m, f.year ?? 0),
    0,
  );
  const nextYear = fiscalYears.value.length ? maxYear + 1 : 0;
  await ElMessageBox.confirm(`确定开始第 ${nextYear} 财年？`, { type: "info" });
  try {
    await api.post(`/competitions/${selectedComp.value.id}/fiscal-years`, { year: nextYear });
    ElMessage.success(`第 ${nextYear} 财年已开始`);
    refreshAll();
    // 同步刷新顶部标题栏的财年显示
    if (compStore.competitionId) await compStore.loadFiscalYear(compStore.competitionId);
  } catch (e) {
    console.error("Failed to start fiscal year:", e);
  }
}

async function endFiscalYear(fy: any) {
  await ElMessageBox.confirm("确定结束当前财年？此操作不可撤销", { type: "warning" });
  try {
    await api.patch(`/competitions/fiscal-years/${fy.id}`, { status: "CLOSED" });
    ElMessage.success("财年已结束");
    refreshAll();
    // 同步刷新顶部标题栏的财年显示（结束后无进行中财年，将显示“未开启财年”）
    if (compStore.competitionId) await compStore.loadFiscalYear(compStore.competitionId);
  } catch (e) {
    console.error("Failed to end fiscal year:", e);
  }
}
</script>

<style scoped>
.comp-page {
  padding: 0;
}
.comp-section {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  border: 1px solid #e0e0e0;
}
.pm-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.pm-title {
  font-size: 18px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.pm-actions {
  display: flex;
  gap: 8px;
}
.fy-empty {
  text-align: center;
  padding: 40px;
  color: #c0c4cc;
}
.fy-empty p {
  margin-top: 12px;
  font-size: 14px;
}
</style>
