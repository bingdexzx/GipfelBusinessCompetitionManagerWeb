<template>
  <div class="account-management">
    <h2 class="page-title">账号管理</h2>

    <el-tabs v-model="activeTab">
      <!-- 系统账号：不归属任何比赛（全局账号） -->
      <el-tab-pane label="账号（系统）" name="system">
        <div class="toolbar">
          <el-button type="primary" @click="showCreateDialog('system')">新建账号</el-button>
        </div>
        <el-table :data="systemUsers" border stripe style="width: 100%; margin-top: 16px">
          <el-table-column prop="username" label="用户名" />
          <el-table-column prop="displayName" label="显示名称" />
          <el-table-column prop="role" label="角色" class-name="role-col">
            <template #default="{ row }">
              <el-tag :type="roleTag(row.role)">{{ roleLabel(row.role) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="权限" width="150" class-name="perm-col">
            <template #default="{ row }">
              <el-tag :type="permSummary(row).type" size="small">{{
                permSummary(row).text
              }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="createdAt" label="创建时间" />
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="handleEdit(row, 'system')">编辑</el-button>
              <el-button size="small" @click="handleResetPassword(row)">重置密码</el-button>
              <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 比赛用账号：归属于当前选中的比赛，比赛删除时联级删除 -->
      <el-tab-pane label="账号（比赛用）" name="competition">
        <div v-if="!compStore.competitionId" class="no-comp-warning">
          请先在「比赛管理」中选择一个比赛
        </div>
        <template v-else>
          <div class="toolbar">
            <span class="comp-label">所属比赛：{{ competitionName }}</span>
            <el-button type="primary" @click="showCreateDialog('competition')"
              >新建账号（比赛用）</el-button
            >
          </div>
          <el-table :data="competitionUsers" border stripe style="width: 100%; margin-top: 16px">
            <el-table-column prop="username" label="用户名" />
            <el-table-column prop="displayName" label="显示名称" />
            <el-table-column prop="role" label="角色" class-name="role-col">
              <template #default="{ row }">
                <el-tag :type="roleTag(row.role)">{{ roleLabel(row.role) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="权限" width="150" class-name="perm-col">
              <template #default="{ row }">
                <el-tag :type="permSummary(row).type" size="small">{{
                  permSummary(row).text
                }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="createdAt" label="创建时间" />
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="handleEdit(row, 'competition')">编辑</el-button>
                <el-button size="small" @click="handleResetPassword(row)">重置密码</el-button>
                <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建 / 编辑账号 -->
    <el-dialog append-to-body v-model="dialogVisible" :title="dialogTitle" width="720px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px" @submit.prevent>
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" :disabled="isEdit" />
        </el-form-item>
        <el-form-item v-if="!isEdit" label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password />
          <div class="form-tip">密码至少 8 位，且含字母和数字</div>
        </el-form-item>
        <el-form-item label="显示名称" prop="displayName">
          <el-input v-model="form.displayName" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role">
            <el-option
              label="超级管理员"
              value="SUPER_ADMIN"
              :disabled="createScope === 'competition'"
            />
            <el-option label="管理员" value="COMPETITION_ADMIN" />
            <el-option label="参赛选手" value="PLAYER" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="createScope === 'competition'" label="所属比赛">
          <el-input :model-value="competitionName" disabled />
        </el-form-item>

        <el-divider content-position="left">账号权限</el-divider>
        <div v-if="form.role === 'SUPER_ADMIN'" class="perm-note">
          超级管理员默认拥有全部权限，无需单独配置。
        </div>
        <template v-else>
          <el-form-item :label="companyScopeLabel">
            <el-select
              v-model="managedCompanies"
              multiple
              filterable
              :placeholder="companyScopePlaceholder"
              style="width: 100%"
            >
              <el-option v-for="c in companyOptions" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>
          <div class="perm-note">{{ companyScopeHint }}</div>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { usersApi, companiesApi } from "@/api";
import { useCompetitionStore } from "@/stores/competition";
import type { FormInstance } from "element-plus";
import { useResourceChanged } from "@/realtime/useResourceChanged";

// 范围字段在 API 中以作用域对象形式返回（与后端正交）：{ mode, companyIds }
interface ScopeLike {
  mode?: "none" | "company" | "all";
  companyIds?: number[];
}
interface UserItem {
  id: number;
  username: string;
  role: string;
  displayName?: string;
  competitionId?: number | null;
  permissions?: string[];
  companyScopes?: ScopeLike;
  viewCompanyScopes?: ScopeLike;
  contractViewCompanyScopes?: ScopeLike;
  createdAt?: string;
}

interface CompanyOption {
  id: number;
  name: string;
}

type AccountScope = "system" | "competition";

const compStore = useCompetitionStore();
const competitionId = computed(() => compStore.competitionId);
const competitionName = computed(() => compStore.competitionName);

const activeTab = ref<AccountScope>("system");
const systemUsers = ref<UserItem[]>([]);
const competitionUsers = ref<UserItem[]>([]);

const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const createScope = ref<AccountScope>("system");
const dialogTitle = ref("新建账号");

const form = reactive({ username: "", password: "", displayName: "", role: "PLAYER" });
const formRules = {
  username: [{ required: true, message: "请输入用户名", trigger: "blur" }],
  password: [
    { required: true, message: "请输入密码", trigger: "blur" },
    { min: 8, max: 64, message: "密码长度需 8-64 位", trigger: "blur" },
    { pattern: /^(?=.*[a-zA-Z])(?=.*\d).+$/, message: "密码需同时包含字母和数字", trigger: "blur" },
  ],
};

// 简化权限：身份(role) + 所选公司 → 自动派生权限与四个范围
const managedCompanies = ref<number[]>([]);
const companyOptions = ref<CompanyOption[]>([]);
let companiesLoaded = false;

/**
 * 根据身份与所选公司派生权限集合与四个范围。
 * - SUPER_ADMIN：空（隐式全权限）。
 * - COMPETITION_ADMIN（管理员）：数据管理查看 + 创建/执行/审核合同（contract:execute 为比赛级执行，不受公司范围限制）+ 查看公司字段 + 股票低级管理+查看 + 区域总览 + 消息；
 *   四个范围（审核/字段查看/合同查看/股票）均 = 所选公司；因持有 contract:execute，合同执行与列表可见性不受 companyScopes 限制。
 * - PLAYER（选手）：数据管理查看 + 消息 + 区域总览；可查看所选公司的合同与全量字段；行情中交易（自身账户）。
 *   四个范围均 = 所选公司（股票范围在仅持 stock:view 时为惰性，不影响权限）。
 */
function derivePermissions(
  role: string,
  companies: number[],
): {
  permissions: string[];
  companyScopes: number[];
  viewCompanyScopes: number[];
  contractViewCompanyScopes: number[];
  stockCompanyScopes: number[];
} {
  if (role === "SUPER_ADMIN") {
    return {
      permissions: [],
      companyScopes: [],
      viewCompanyScopes: [],
      contractViewCompanyScopes: [],
      stockCompanyScopes: [],
    };
  }
  const baseView = [
    "data:material:view",
    "data:part:view",
    "data:product:view",
    "data:map:view",
    "data:infrastructure:view",
    "data:tech:view",
    "data:fuel:view",
    "data:vehicle:view",
    "data:warehouse:view",
    "data:productionLine:view",
    "data:region:view",
    "industryType:view",
    "contractType:view",
    "company:view",
    "contract:view",
    "message:view",
    "stock:view",
  ];
  if (role === "COMPETITION_ADMIN") {
    return {
      permissions: [...baseView, "contract:manage", "contract:audit", "contract:execute", "stock:edit"],
      companyScopes: companies,
      viewCompanyScopes: companies,
      contractViewCompanyScopes: companies,
      stockCompanyScopes: companies,
    };
  }
  // PLAYER：仅查看/行情 + 自选公司合同与字段；不做合同审核
  return {
    permissions: [...baseView],
    companyScopes: [],
    viewCompanyScopes: companies,
    contractViewCompanyScopes: companies,
    stockCompanyScopes: companies,
  };
}

async function loadCompanies() {
  if (companiesLoaded) return;
  try {
    const list = await companiesApi.list();
    companyOptions.value = (list || []).map((c: any) => ({ id: c.id, name: c.name }));
    companiesLoaded = true;
  } catch (e) {
    console.error("加载公司列表失败:", e);
  }
}

// 公司选择框的标签/提示随身份变化（管理员=“管理的公司”，选手=“可查看/操作的公司”）
const companyScopeLabel = computed(() =>
  form.role === "COMPETITION_ADMIN" ? "管理的公司" : "可查看/操作的公司",
);
const companyScopePlaceholder = computed(() =>
  form.role === "COMPETITION_ADMIN" ? "选择该管理员可管理的公司" : "选择该选手可查看/操作的公司",
);
const companyScopeHint = computed(() => {
  if (form.role === "COMPETITION_ADMIN") {
    return "权限自动派生：数据管理全部查看、创建/审核（参与方之一为所选公司）合同、查看所选公司全量字段、所选公司的股票低级管理与行情、区域总览与消息。";
  }
  return "权限自动派生：数据管理全部查看、区域总览与消息；可查看所选公司的合同与全量字段，并在行情中交易自己的资金账户。";
});

function roleTag(role: string) {
  const map: Record<string, string> = {
    SUPER_ADMIN: "danger",
    COMPETITION_ADMIN: "warning",
    PLAYER: "info",
  };
  return map[role] || "info";
}

function roleLabel(role: string) {
  const map: Record<string, string> = {
    SUPER_ADMIN: "超级管理员",
    COMPETITION_ADMIN: "管理员",
    PLAYER: "参赛选手",
  };
  return map[role] || role;
}

function permSummary(row: UserItem) {
  if (row.role === "SUPER_ADMIN") return { text: "全部权限", type: "danger" };
  const n = row.viewCompanyScopes?.companyIds?.length || 0;
  if (row.role === "COMPETITION_ADMIN") return { text: `管理员·${n} 公司`, type: "warning" };
  return { text: `选手·${n} 公司`, type: "info" };
}

async function loadSystemUsers() {
  try {
    const res = await usersApi.list({ competitionId: "null" });
    // 后端返回 { items, total } 分页对象，但 cachedApi 已把列表响应降维为裸数组，
    // 故 res 可能是数组；统一兼容两种形态。
    systemUsers.value = Array.isArray(res) ? res : res?.items ?? [];
  } catch (e) {
    console.error("加载系统账号失败:", e);
  }
}

async function loadCompetitionUsers() {
  if (!competitionId.value) {
    competitionUsers.value = [];
    return;
  }
  try {
    const res = await usersApi.list({ competitionId: competitionId.value });
    competitionUsers.value = Array.isArray(res) ? res : res?.items ?? [];
  } catch (e) {
    console.error("加载比赛账号失败:", e);
  }
}

async function loadAll() {
  await Promise.all([loadSystemUsers(), loadCompetitionUsers()]);
}

function showCreateDialog(scope: AccountScope) {
  createScope.value = scope;
  isEdit.value = false;
  editingId.value = null;
  dialogTitle.value = scope === "competition" ? "新建账号（比赛用）" : "新建账号";
  form.username = "";
  form.password = "";
  form.displayName = "";
  form.role = "PLAYER";
  managedCompanies.value = [];
  loadCompanies();
  dialogVisible.value = true;
}

function handleEdit(row: UserItem, scope: AccountScope) {
  createScope.value = scope;
  isEdit.value = true;
  editingId.value = row.id;
  dialogTitle.value = "编辑账号";
  form.username = row.username;
  form.displayName = row.displayName || "";
  form.role = row.role;
  form.password = "";
  // 编辑时以「可查看字段范围」还原公司多选（四个范围在派生时一致）。
  // 注意 viewCompanyScopes 是作用域对象 { mode, companyIds }，需取 companyIds。
  managedCompanies.value = [...(row.viewCompanyScopes?.companyIds || [])];
  loadCompanies();
  dialogVisible.value = true;
}

function handleResetPassword(row: UserItem) {
  ElMessageBox.prompt("请输入新密码（至少 8 位，含字母和数字）", "重置密码", {
    confirmButtonText: "确定",
    inputType: "password",
    inputValidator: (val: string) =>
      val && /^(?=.*[a-zA-Z])(?=.*\d).{8,64}$/.test(val) ? true : "密码需 8-64 位且含字母和数字",
  })
    .then(async ({ value }) => {
      await usersApi.updatePassword(row.id, { password: value });
      ElMessage.success("密码已重置");
    })
    .catch(() => {});
}

function handleDelete(row: UserItem) {
  ElMessageBox.confirm(`确定删除用户 "${row.username}" 吗？`, "确认删除", { type: "warning" })
    .then(async () => {
      await usersApi.remove(row.id);
      ElMessage.success("已删除");
      loadAll();
    })
    .catch(() => {});
}

async function handleSubmit() {
  if (!formRef.value) return;
  await formRef.value.validate(async (valid) => {
    if (!valid) return;
    submitting.value = true;
    try {
      const derived = derivePermissions(form.role, managedCompanies.value);
      if (isEdit.value && editingId.value) {
        await usersApi.update(editingId.value, {
          role: form.role,
          displayName: form.displayName,
          permissions: derived.permissions,
          companyScopes: derived.companyScopes,
          viewCompanyScopes: derived.viewCompanyScopes,
          contractViewCompanyScopes: derived.contractViewCompanyScopes,
          stockCompanyScopes: derived.stockCompanyScopes,
        });
      } else {
        const payload: Record<string, unknown> = {
          username: form.username,
          password: form.password,
          displayName: form.displayName,
          role: form.role,
          permissions: derived.permissions,
          companyScopes: derived.companyScopes,
          viewCompanyScopes: derived.viewCompanyScopes,
          contractViewCompanyScopes: derived.contractViewCompanyScopes,
          stockCompanyScopes: derived.stockCompanyScopes,
          competitionId:
            createScope.value === "competition" && competitionId.value
              ? competitionId.value
              : undefined,
        };
        await usersApi.create(payload);
      }
      ElMessage.success(isEdit.value ? "已更新" : "已创建");
      dialogVisible.value = false;
      loadAll();
    } catch {
      ElMessage.error("操作失败，请重试");
    } finally {
      submitting.value = false;
    }
  });
}

function resetForm() {
  formRef.value?.resetFields();
}

// 切换比赛时刷新“比赛用账号”列表
watch(competitionId, () => {
  loadCompetitionUsers();
});

onMounted(loadAll);

useResourceChanged("users", () => {
  loadAll();
});
</script>

<style scoped>
.page-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0 0 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.comp-label {
  font-size: 14px;
  color: #606266;
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
.form-tip {
  font-size: 12px;
  line-height: 1.4;
  color: #909399;
  margin-top: 4px;
}
.perm-note {
  padding: 10px 14px;
  background: #f4f4f5;
  border-radius: 6px;
  color: #909399;
  font-size: 13px;
}
/* 角色栏：收紧单元格左右内边距（默认 12px → 4px），标签更贴边 */
:deep(.role-col .cell) {
  padding-left: 4px;
  padding-right: 4px;
}
/* 权限栏：加大单元格左右内边距（默认 12px → 22px），标签更舒展 */
:deep(.perm-col .cell) {
  padding-left: 22px;
  padding-right: 22px;
}
</style>
