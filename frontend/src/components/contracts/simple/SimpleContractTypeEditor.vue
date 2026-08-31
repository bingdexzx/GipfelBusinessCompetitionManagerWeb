<template>
  <div class="simple-contract-type-editor">
    <el-form :model="form" label-width="120px" @submit.prevent>
      <!-- 基本信息 -->
      <el-divider>基本信息</el-divider>
      <el-form-item label="标识(key)" required>
        <el-input v-model="form.key" disabled placeholder="自动生成（名称拼音）" />
      </el-form-item>
      <el-form-item label="名称" required>
        <el-input v-model="form.name" placeholder="合同类型名称" />
      </el-form-item>
      <el-form-item label="说明">
        <el-input v-model="form.description" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item label="启用">
        <el-switch v-model="form.enabled" />
      </el-form-item>

      <!-- 参与方角色 -->
      <el-divider>参与方角色</el-divider>
      <el-table :data="form.partyRoles" border size="small">
        <el-table-column prop="role" label="角色标识" width="120">
          <template #default="{ row }">
            <el-input v-model="row.role" size="small" />
          </template>
        </el-table-column>
        <el-table-column prop="label" label="显示名称">
          <template #default="{ row }">
            <el-input v-model="row.label" size="small" />
          </template>
        </el-table-column>
        <el-table-column prop="isHost" label="主办方" width="100">
          <template #default="{ row }">
            <el-switch v-model="row.isHost" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ $index }">
            <el-button size="small" type="danger" text @click="removeParty($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-button style="margin-top: 8px" @click="addParty">添加参与方</el-button>

      <!-- 输入字段 -->
      <el-divider>输入字段</el-divider>
      <el-table :data="form.inputSchema" border size="small">
        <el-table-column prop="key" label="字段标识" width="120">
          <template #default="{ row }">
            <el-input v-model="row.key" size="small" />
          </template>
        </el-table-column>
        <el-table-column prop="label" label="显示名称" width="150">
          <template #default="{ row }">
            <el-input v-model="row.label" size="small" />
          </template>
        </el-table-column>
        <el-table-column prop="type" label="类型" width="120">
          <template #default="{ row }">
            <el-select v-model="row.type" size="small">
              <el-option label="数字" value="NUMBER" />
              <el-option label="文本" value="STRING" />
              <el-option label="布尔" value="BOOLEAN" />
              <el-option label="单选" value="SELECT" />
              <el-option label="公司引用" value="COMPANY_REF" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column prop="required" label="必填" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.required" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ $index }">
            <el-button size="small" type="danger" text @click="removeInput($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-button style="margin-top: 8px" @click="addInput">添加输入字段</el-button>

      <!-- 效果定义 -->
      <el-divider>效果定义</el-divider>
      <div v-for="(effect, idx) in form.effects" :key="idx" class="effect-item">
        <el-card shadow="never">
          <template #header>
            <div class="effect-header">
              <span>效果 {{ idx + 1 }}</span>
              <el-button size="small" type="danger" text @click="removeEffect(idx)">删除</el-button>
            </div>
          </template>
          <el-form-item label="参与方">
            <el-select v-model="effect.party" size="small">
              <el-option v-for="p in form.partyRoles" :key="p.role" :label="p.label" :value="p.role" />
            </el-select>
          </el-form-item>
          <el-form-item label="字段标识">
            <el-input v-model="effect.fieldKey" size="small" placeholder="产业字段 fieldKey" />
          </el-form-item>
          <el-form-item label="操作类型">
            <el-select v-model="effect.op" size="small">
              <el-option label="增加" value="ADD" />
              <el-option label="减少" value="SUB" />
              <el-option label="设置" value="SET" />
            </el-select>
          </el-form-item>
          <el-form-item label="值">
            <FormulaInput v-model="effect.value" :inputs="form.inputSchema" />
          </el-form-item>
        </el-card>
      </div>
      <el-button style="margin-top: 8px" @click="addEffect">添加效果</el-button>

      <!-- 检查定义 -->
      <el-divider>检查定义</el-divider>
      <div v-for="(chk, idx) in form.checks" :key="idx" class="effect-item">
        <el-card shadow="never">
          <template #header>
            <div class="effect-header">
              <span>检查 {{ idx + 1 }}</span>
              <el-button size="small" type="danger" text @click="removeCheck(idx)">删除</el-button>
            </div>
          </template>
          <el-form-item label="参与方">
            <el-select v-model="chk.party" size="small">
              <el-option v-for="p in form.partyRoles" :key="p.role" :label="p.label" :value="p.role" />
            </el-select>
          </el-form-item>
          <el-form-item label="字段标识">
            <el-input v-model="chk.fieldKey" size="small" placeholder="产业字段 fieldKey" />
          </el-form-item>
          <el-form-item label="运算符">
            <el-select v-model="chk.op" size="small">
              <el-option label="≥（大于等于）" value="GTE" />
              <el-option label="≤（小于等于）" value="LTE" />
              <el-option label="＞（大于）" value="GT" />
              <el-option label="＜（小于）" value="LT" />
              <el-option label="＝（等于）" value="EQ" />
            </el-select>
          </el-form-item>
          <el-form-item label="值">
            <FormulaInput v-model="chk.value" :inputs="form.inputSchema" />
          </el-form-item>
          <el-form-item label="不通过提示">
            <el-input v-model="chk.errorMessage" size="small" placeholder="留空则用系统默认说明" />
          </el-form-item>
        </el-card>
      </div>
      <el-button style="margin-top: 8px" @click="addCheck">添加检查</el-button>
      <el-alert
        v-if="preservedConditions.length"
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 8px"
        title="该合同类型含有专家模式创建的其它检查（非「产业字段比较」），已在保存时原样保留，不会在简单模式下编辑。"
      />
    </el-form>

    <div class="editor-actions">
      <el-button @click="$emit('cancel')">取消</el-button>
      <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue';
import { ElMessage } from 'element-plus';
import FormulaInput from './FormulaInput.vue';
import { toPinyinKey } from '@/utils/pinyin';

interface PartyRole {
  role: string;
  label: string;
  selectable: boolean;
  isHost: boolean;
}

interface InputField {
  key: string;
  label: string;
  type: string;
  required: boolean;
  default?: any;
}

interface FieldEffect {
  type: 'FIELD';
  party: string;
  fieldKey: string;
  op: 'ADD' | 'SUB' | 'SET';
  value: any;
}

interface FieldCheck {
  kind: 'FIELD_COMPARE';
  party: string;
  fieldKey: string;
  op: 'GTE' | 'LTE' | 'GT' | 'LT' | 'EQ';
  value: any;
  label?: string;
  errorMessage?: string;
}

const props = defineProps<{
  contractType?: any;
}>();

const emit = defineEmits<{
  (e: 'saved', data: any): void;
  (e: 'cancel'): void;
}>();

const saving = ref(false);

const form = reactive({
  key: '',
  name: '',
  description: '',
  enabled: true,
  partyRoles: [] as PartyRole[],
  inputSchema: [] as InputField[],
  effects: [] as FieldEffect[],
  checks: [] as FieldCheck[],
});

// 专家模式创建的、简单模式无法编辑的检查（如 VALUE_COMPARE / INDUSTRY_IS 等）原样保留。
const preservedConditions = ref<any[]>([]);

// 初始化表单
watch(() => props.contractType, (ct) => {
  if (ct) {
    form.key = ct.key || '';
    form.name = ct.name || '';
    form.description = ct.description || '';
    form.enabled = ct.enabled ?? true;
    form.partyRoles = Array.isArray(ct.partyRoles) ? ct.partyRoles.map((p: any) => ({ ...p })) : [];
    form.inputSchema = Array.isArray(ct.inputSchema) ? ct.inputSchema.map((f: any) => ({ ...f })) : [];
    form.effects = Array.isArray(ct.effects) ? ct.effects.filter((e: any) => e.type === 'FIELD').map((e: any) => ({ ...e })) : [];
    const conds = Array.isArray(ct.conditions) ? ct.conditions : [];
    form.checks = conds
      .filter((c: any) => c.kind === 'FIELD_COMPARE')
      .map((c: any) => ({
        kind: 'FIELD_COMPARE' as const,
        party: c.party || '',
        fieldKey: c.fieldKey || '',
        op: (c.op || 'GTE') as FieldCheck['op'],
        value: c.value ? { ...c.value } : { type: 'CONST', value: 0 },
        label: c.label || '',
        errorMessage: c.errorMessage || '',
      }));
    preservedConditions.value = conds.filter((c: any) => c.kind !== 'FIELD_COMPARE');
  } else {
    form.key = '';
    form.name = '';
    form.description = '';
    form.enabled = true;
    form.partyRoles = [];
    form.inputSchema = [];
    form.effects = [];
    form.checks = [];
    preservedConditions.value = [];
  }
}, { immediate: true });

// 新建时：输入名称实时用拼音自动生成 key（编辑态 key 只读，不覆盖）
watch(
  () => form.name,
  () => {
    if (!props.contractType) {
      form.key = (form.name || '').trim() ? toPinyinKey(form.name.trim()) : '';
    }
  },
);

function addParty() {
  form.partyRoles.push({ role: '', label: '', selectable: true, isHost: false });
}

function removeParty(index: number) {
  form.partyRoles.splice(index, 1);
}

function addInput() {
  form.inputSchema.push({ key: '', label: '', type: 'NUMBER', required: false });
}

function removeInput(index: number) {
  form.inputSchema.splice(index, 1);
}

function addEffect() {
  form.effects.push({
    type: 'FIELD',
    party: form.partyRoles[0]?.role || '',
    fieldKey: '',
    op: 'ADD',
    value: { type: 'CONST', value: 0 },
  });
}

function removeEffect(index: number) {
  form.effects.splice(index, 1);
}

function addCheck() {
  form.checks.push({
    kind: 'FIELD_COMPARE',
    party: form.partyRoles[0]?.role || '',
    fieldKey: '',
    op: 'GTE',
    value: { type: 'CONST', value: 0 },
    label: '',
    errorMessage: '',
  });
}

function removeCheck(index: number) {
  form.checks.splice(index, 1);
}

async function handleSave() {
  // 基本校验
  if (!form.name.trim()) {
    ElMessage.error('请输入合同类型名称');
    return;
  }
  // 标识(key) 兜底：新建时若尚未自动生成，按名称拼音生成
  if (!form.key.trim()) {
    form.key = toPinyinKey(form.name.trim());
  }
  if (form.partyRoles.length === 0) {
    ElMessage.error('至少需要一个参与方角色');
    return;
  }
  for (const p of form.partyRoles) {
    if (!p.role.trim() || !p.label.trim()) {
      ElMessage.error('参与方角色标识和名称不能为空');
      return;
    }
  }
  for (const chk of form.checks) {
    if (!chk.party) {
      ElMessage.error('检查需要选择参与方');
      return;
    }
    if (!chk.fieldKey.trim()) {
      ElMessage.error('检查的字段标识不能为空');
      return;
    }
  }

  saving.value = true;
  try {
    const data = {
      key: form.key,
      name: form.name,
      description: form.description,
      enabled: form.enabled,
      partyRoles: form.partyRoles,
      inputSchema: form.inputSchema,
      effects: form.effects,
      conditions: [...preservedConditions.value, ...form.checks],
      graph: props.contractType?.graph || null,
    };
    emit('saved', data);
  } finally {
    saving.value = false;
  }
}
</script>

<style scoped>
.simple-contract-type-editor {
  padding: 16px;
}

.effect-item {
  margin-bottom: 12px;
}

.effect-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.editor-actions {
  margin-top: 24px;
  text-align: right;
}

.json-box {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 4px;
  font-family: monospace;
  font-size: 12px;
  overflow-x: auto;
  max-height: 200px;
}
</style>
