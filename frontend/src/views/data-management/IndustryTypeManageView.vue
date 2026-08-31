<template>
  <div class="it-manager">
    <h2 class="page-title">产业类型管理</h2>
    <div class="toolbar">
      <el-input
        v-model="searchText"
        placeholder="搜索名称 / 编号"
        clearable
        style="width: 200px"
      />
      <el-button
        type="primary"
        :disabled="!authStore.can('industryType:manage')"
        @click="openCreate"
        >新建产业类型</el-button
      >
    </div>

    <el-alert
      v-if="!loading && types.length === 0"
      type="info"
      show-icon
      :closable="false"
      title="暂无产业类型"
      style="margin-bottom: 12px"
    />

    <el-table
      v-loading="loading"
      :data="filteredTypes"
      border
      stripe
      row-key="id"
      style="width: 100%"
    >
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand-fields">
            <div v-if="!row.fields || row.fields.length === 0" class="empty-tip">
              该产业尚未定义字段
            </div>
            <el-table v-else :data="row.fields" size="small" border>
              <el-table-column prop="name" label="字段名称" min-width="140" />
              <el-table-column prop="fieldKey" label="字段键" min-width="140" />
              <el-table-column prop="fieldType" label="类型" width="100" />
              <el-table-column label="默认值" min-width="100">
                <template #default="{ row: f }">{{ f.defaultValue ?? "—" }}</template>
              </el-table-column>
              <el-table-column label="计算字段" width="120">
                <template #default="{ row: f }">
                  <el-tag v-if="f.isCalculated" size="small" type="warning">公式</el-tag>
                  <span v-else>—</span>
                </template>
              </el-table-column>
              <el-table-column prop="formula" label="计算配置" min-width="160">
                <template #default="{ row: f }">{{ formulaDisplay(f) }}</template>
              </el-table-column>
              <el-table-column label="配置" min-width="200">
                <template #default="{ row: f }">{{ configSummary(f) }}</template>
              </el-table-column>
              <el-table-column label="定时器" width="110">
                <template #default="{ row: f }">
                  <el-tag v-if="f.timerEnabled" size="small" type="success">
                    {{ f.timerTrigger === "FY_END" ? "财年末" : "财年初" }}
                  </el-tag>
                  <span v-else>—</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="code" label="编号" width="90" />
      <el-table-column prop="name" label="产业名称" min-width="180" />
      <el-table-column label="说明" min-width="220">
        <template #default="{ row }">{{ row.description || "—" }}</template>
      </el-table-column>
      <el-table-column label="字段数" width="90">
        <template #default="{ row }">{{ row.fields?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="公司数" width="90">
        <template #default="{ row }">{{ row._count?.companies ?? 0 }}</template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openTypeDetail(row)">详情</el-button>
          <el-button size="small" @click="openFields(row)">字段</el-button>
          <el-button
            size="small"
            type="primary"
            :disabled="!authStore.can('industryType:manage')"
            @click="openEdit(row)"
            >编辑</el-button
          >
          <el-button
            size="small"
            type="danger"
            :disabled="!authStore.can('industryType:manage')"
            @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建 / 编辑产业类型 -->
    <el-dialog append-to-body
      v-model="showForm"
      :title="editingId ? '编辑产业类型' : '新建产业类型'"
      width="520px"
    >
      <el-form :model="form" label-width="90px">
        <el-form-item label="产业名称" required>
          <el-input v-model="form.name" placeholder="如：新能源产业" />
        </el-form-item>
        <el-form-item label="编号">
          <el-input-number v-model="form.code" :min="1" :controls="false" style="width: 100%" />
          <div class="hint">留空则自动分配（当前最大编号 +1）</div>
        </el-form-item>
        <el-form-item label="说明">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            placeholder="该产业的职责说明"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 产业字段管理 -->
    <el-dialog append-to-body v-model="showFields" :title="`产业字段 · ${fieldTarget?.name || ''}`" width="900px">
      <el-table v-loading="fieldLoading" :data="fields" border size="small">
        <el-table-column prop="name" label="字段名称" min-width="130" />
        <el-table-column prop="fieldKey" label="字段键" min-width="130" />
        <el-table-column prop="fieldType" label="类型" width="90" />
        <el-table-column label="默认值" width="100">
          <template #default="{ row }">{{ row.defaultValue ?? "—" }}</template>
        </el-table-column>
        <el-table-column label="计算配置" min-width="150">
          <template #default="{ row }">{{ formulaDisplay(row) }}</template>
        </el-table-column>
        <el-table-column label="配置" min-width="200">
          <template #default="{ row }">{{ configSummary(row) }}</template>
        </el-table-column>
        <el-table-column label="定时器" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.timerEnabled" size="small" type="success">
              {{ row.timerTrigger === "FY_END" ? "财年末" : "财年初" }}
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="sortOrder" label="排序" width="70" />
        <el-table-column label="展示" width="80">
          <template #default="{ row }">
            <el-switch
              :model-value="row.visible !== false"
              :disabled="!authStore.can('industryType:manage')"
              @change="(v: any) => toggleFieldVisible(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openFieldDetail(row)">详情</el-button>
            <template v-if="row.isCalculated">
              <el-button
                size="small"
                type="primary"
                :disabled="!authStore.can('industryType:manage')"
                @click="openGraphFullscreen(row)"
                >编辑公式</el-button
              >
            </template>
            <template v-else>
              <el-button
                size="small"
                :disabled="!authStore.can('industryType:manage')"
                @click="editField(row)"
                >编辑</el-button
              >
            </template>
            <el-button
              size="small"
              type="danger"
              :disabled="!authStore.can('industryType:manage')"
              @click="deleteField(row)"
              >删除</el-button
            >
          </template>
        </el-table-column>
      </el-table>

      <el-divider>{{ fieldForm.id ? "编辑字段" : "添加字段" }}</el-divider>
      <el-form
        :model="fieldForm"
        label-width="90px"
        :disabled="!authStore.can('industryType:manage')"
        @submit.prevent
      >
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="字段名称" required>
              <el-input v-model="fieldForm.name" placeholder="如：矿点数量" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="字段键">
              <el-input
                v-model="fieldForm.fieldKey"
                placeholder="自动生成"
                disabled
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="类型">
              <el-select
                v-model="fieldForm.fieldType"
                style="width: 100%"
                @change="onFieldTypeChange"
              >
                <el-option label="数值 NUMBER" value="NUMBER" />
                <el-option label="文本 STRING" value="STRING" />
                <el-option label="布尔 BOOLEAN" value="BOOLEAN" />
                <el-option label="字典 DICTIONARY" value="DICTIONARY" />
                <el-option label="列表 LIST" value="LIST" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 字典字段配置 -->
        <el-row v-if="fieldForm.fieldType === 'DICTIONARY'" :gutter="12">
          <el-col :span="24">
            <el-form-item label="值类型">
              <el-select v-model="fieldForm.config.valueType" style="width: 200px">
                <el-option label="数值 NUMBER" value="NUMBER" />
                <el-option label="文本 STRING" value="STRING" />
                <el-option label="布尔 BOOLEAN" value="BOOLEAN" />
              </el-select>
              <span class="hint">字典中每个键对应的值的类型</span>
            </el-form-item>
            <el-form-item label="字典项">
              <div v-for="(e, idx) in fieldForm.config.entries" :key="idx" class="dict-row">
                <el-input
                  v-model="e.key"
                  placeholder="key（字母/数字/下划线）"
                  style="width: 150px"
                />
                <el-input v-model="e.label" placeholder="显示名" style="width: 150px" />
                <el-input v-model="e.defaultValue" placeholder="默认值" style="width: 140px" />
                <el-button type="danger" size="small" @click="removeDictEntry(idx)">删</el-button>
              </div>
              <el-button size="small" native-type="button" @click="addDictEntry"
                >+ 添加字典项</el-button
              >
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 列表字段配置 -->
        <el-row v-if="fieldForm.fieldType === 'LIST'" :gutter="12">
          <el-col :span="8">
            <el-form-item label="列表项类型">
              <el-select v-model="fieldForm.config.itemType" style="width: 100%">
                <el-option label="数值 NUMBER" value="NUMBER" />
                <el-option label="文本 STRING" value="STRING" />
                <el-option label="布尔 BOOLEAN" value="BOOLEAN" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="默认值">
              <el-input v-model="fieldForm.defaultValue" placeholder="可留空" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="排序">
              <el-input-number
                v-model="fieldForm.sortOrder"
                :min="0"
                :controls="false"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="计算字段">
              <el-switch v-model="fieldForm.isCalculated" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="前台展示">
              <el-switch v-model="fieldForm.visible" />
              <span class="hint"
                >关闭后该字段在公司管理、区域总览、合同编辑器等所有客户端界面均不显示（仍可被子合同引擎改写）</span
              >
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 财年定时器：启用后于财年「开始/结束」时自动把该字段写为设定值（作用范围：该产业类型的全部公司） -->
        <el-row :gutter="12">
          <el-col :span="24">
            <el-form-item label="财年定时器">
              <el-switch
                v-model="fieldForm.timerEnabled"
                :disabled="fieldForm.isCalculated"
              />
              <span class="hint" v-if="fieldForm.isCalculated"
                >计算字段不支持定时器（定时器写入值会被级联重算覆盖）</span
              >
              <span class="hint" v-else
                >启用后，在财年「开始 / 结束」时自动把该字段写为下方设定值（作用范围：该产业类型的全部公司）</span
              >
            </el-form-item>
          </el-col>
        </el-row>
        <el-row v-if="fieldForm.timerEnabled && !fieldForm.isCalculated" :gutter="12">
          <el-col :span="8">
            <el-form-item label="触发时机">
              <el-select v-model="fieldForm.timerTrigger" style="width: 100%">
                <el-option label="财年开始" value="FY_START" />
                <el-option label="财年结束" value="FY_END" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="16">
            <el-form-item label="设定值">
              <div class="timer-value-wrap">
                <el-radio-group v-model="timerValueMode" size="small">
                  <el-radio-button value="const">常量值</el-radio-button>
                  <el-radio-button value="field">引用本产业字段</el-radio-button>
                </el-radio-group>
                <template v-if="timerValueMode === 'field'">
                  <el-select
                    v-model="timerValueRef"
                    placeholder="选择本产业同类型字段"
                    style="width: 100%; margin-top: 8px"
                  >
                    <el-option
                      v-for="f in timerRefCandidates"
                      :key="f.fieldKey"
                      :label="`${f.name}（${f.fieldKey}）`"
                      :value="f.fieldKey"
                    />
                  </el-select>
                  <span class="hint">触发时把该字段写为所选字段的当前值</span>
                </template>
                <template v-else>
                  <el-input
                    v-if="fieldForm.fieldType === 'NUMBER'"
                    v-model="fieldForm.timerValue"
                    placeholder="数值，如 100"
                    style="margin-top: 8px"
                  />
                  <el-switch
                    v-else-if="fieldForm.fieldType === 'BOOLEAN'"
                    :model-value="fieldForm.timerValue === 'true'"
                    @change="(v: any) => (fieldForm.timerValue = v ? 'true' : 'false')"
                    style="margin-top: 8px"
                  />
                  <el-input
                    v-else-if="fieldForm.fieldType === 'DICTIONARY' || fieldForm.fieldType === 'LIST'"
                    v-model="fieldForm.timerValue"
                    type="textarea"
                    :rows="2"
                    :placeholder="timerValuePlaceholder"
                    style="margin-top: 8px"
                  />
                  <el-input
                    v-else
                    v-model="fieldForm.timerValue"
                    placeholder="文本"
                    style="margin-top: 8px"
                  />
                </template>
              </div>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item v-if="fieldForm.isCalculated" label="计算图">
          <div style="width: 100%">
            <el-button type="primary" @click="showGraphFullscreen = true">打开编辑器</el-button>
            <div class="fb-readout" style="margin-top: 12px">
              <div class="fb-readout-title">
                当前产业计算图：{{ fieldForm.calcGraph ? "已配置" : "（未配置）" }}
              </div>
              <pre class="fb-json">{{ fieldForm.calcGraph || "（空）" }}</pre>
            </div>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button v-if="fieldForm.id" @click="resetFieldForm">取消编辑</el-button>
        <el-button
          type="primary"
          :loading="fieldSaving"
          :disabled="!authStore.can('industryType:manage')"
          @click="submitField"
          >{{ fieldForm.id ? "保存修改" : "添加字段" }}</el-button
        >
      </template>
    </el-dialog>

    <!-- 全屏蓝图编辑器（计算字段）：左侧：字段细节；主区：蓝图画布 -->
    <el-dialog
      append-to-body
      class="fs-dialog"
      v-model="showGraphFullscreen"
      fullscreen
      :show-close="false"
      title=""
    >
      <div class="fs-wrap">
        <div class="fs-topbar">
          <div class="fs-title">
            <span class="fs-title-main">产业计算字段 · {{ fieldForm.name || "未命名字段" }}</span>
            <el-tag v-if="fieldForm.isCalculated" size="small" type="warning">计算公式</el-tag>
          </div>
          <div class="fs-actions">
            <el-button @click="showGraphFullscreen = false">关闭</el-button>
            <el-button
              type="primary"
              :loading="fieldSaving"
              :disabled="!authStore.can('industryType:manage')"
              @click="submitField"
              >保存</el-button
            >
          </div>
        </div>
        <div class="fs-main">
          <!-- 左侧：字段细节 -->
          <div class="fs-details">
            <div class="fs-details-title">字段细节</div>
            <el-form :model="fieldForm" label-width="72px" size="small" class="fs-details-form">
              <el-form-item label="字段名称" required>
                <el-input v-model="fieldForm.name" placeholder="如：矿点数量" />
              </el-form-item>
              <el-form-item label="字段键">
                <el-input
                  v-model="fieldForm.fieldKey"
                  placeholder="自动生成"
                  disabled
                />
              </el-form-item>
              <el-form-item label="类型">
                <el-select
                  v-model="fieldForm.fieldType"
                  style="width: 100%"
                  @change="onFieldTypeChange"
                >
                  <el-option label="数值 NUMBER" value="NUMBER" />
                  <el-option label="文本 STRING" value="STRING" />
                  <el-option label="布尔 BOOLEAN" value="BOOLEAN" />
                  <el-option label="字典 DICTIONARY" value="DICTIONARY" />
                  <el-option label="列表 LIST" value="LIST" />
                </el-select>
              </el-form-item>
              <el-form-item label="默认值">
                <el-input v-model="fieldForm.defaultValue" placeholder="可留空" />
              </el-form-item>
              <el-form-item label="排序">
                <el-input-number
                  v-model="fieldForm.sortOrder"
                  :min="0"
                  :controls="false"
                  style="width: 100%"
                />
              </el-form-item>
              <el-form-item label="前台展示">
                <el-switch v-model="fieldForm.visible" />
              </el-form-item>
              <el-form-item label="计算字段">
                <el-switch v-model="fieldForm.isCalculated" />
              </el-form-item>
            </el-form>
          </div>
          <!-- 主区：公式 / 蓝图 二选一（计算字段） -->
          <div class="fs-editor">
            <template v-if="fieldForm.isCalculated">
              <div class="fs-mode-bar">
                <el-radio-group v-model="fieldForm.editorMode" size="small" @change="onEditorModeChange">
                  <el-radio-button value="formula">公式（Excel 风格）</el-radio-button>
                  <el-radio-button value="graph">蓝图（高级）</el-radio-button>
                </el-radio-group>
                <span class="fs-mode-tip">
                  在公式里直接用其它字段键作变量，如
                  <code>(mineCount + capacity) * 0.5</code>；条件用
                  <code>IF(cond, a, b)</code>。
                </span>
              </div>
              <div v-if="fieldForm.editorMode === 'formula'" class="fs-formula">
                <div class="fs-formula-wrapper">
                  <div class="fs-formula-fields">
                    <span class="fs-formula-fields-title">可用字段：</span>
                    <code
                      v-for="f in formulaFields.filter(f => !f.isCalculated)"
                      :key="f.fieldKey"
                      class="fs-formula-field-key"
                      :title="`${f.name} (${f.fieldType})`"
                      @click="insertFormulaField(f.fieldKey)"
                    >{{ f.fieldKey }}</code>
                    <span v-if="formulaFields.filter(f => !f.isCalculated).length === 0" style="color:#c0c4cc;font-size:12px">暂无可用字段</span>
                  </div>
                  <textarea
                    ref="formulaTextareaRef"
                    class="fs-formula-textarea"
                    :value="fieldForm.formula"
                    @input="fieldForm.formula = ($event.target as HTMLTextAreaElement).value"
                    placeholder="输入公式，例如: (revenue - cost) * (1 - taxRate)&#10;可直接使用字段键作为变量名"
                    spellcheck="false"
                  ></textarea>
                </div>
              </div>
              <IndustryFieldGraphEditor
                v-else
                v-model="fieldForm.calcGraph"
                :available-fields="formulaFields"
                @close="showGraphFullscreen = false"
              />
            </template>
            <el-empty v-else description="勾选左侧「计算字段」后即可用公式或蓝图定义该字段的取值" />
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 产业类型详情（只读） -->
    <el-dialog
      append-to-body
      v-model="typeDetailVisible"
      :title="`产业类型详情 · ${typeDetailRow?.name || ''}`"
      width="820px"
    >
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="编号">{{ typeDetailRow?.code ?? "—" }}</el-descriptions-item>
        <el-descriptions-item label="产业名称">{{ typeDetailRow?.name || "—" }}</el-descriptions-item>
        <el-descriptions-item label="字段数">{{ typeDetailRow?.fields?.length || 0 }}</el-descriptions-item>
        <el-descriptions-item label="公司数">{{ typeDetailRow?._count?.companies ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="说明" :span="2">{{ typeDetailRow?.description || "—" }}</el-descriptions-item>
      </el-descriptions>
      <el-divider content-position="left">字段列表</el-divider>
      <el-table :data="typeDetailRow?.fields || []" border size="small" empty-text="该产业尚未定义字段">
        <el-table-column prop="name" label="字段名称" min-width="130" />
        <el-table-column prop="fieldKey" label="字段键" min-width="130" />
        <el-table-column prop="fieldType" label="类型" width="90" />
        <el-table-column label="默认值" width="100">
          <template #default="{ row }">{{ row.defaultValue ?? "—" }}</template>
        </el-table-column>
        <el-table-column label="计算字段" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.isCalculated" size="small" type="warning">计算</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="计算配置" min-width="150">
          <template #default="{ row }">{{ formulaDisplay(row) }}</template>
        </el-table-column>
        <el-table-column label="配置" min-width="200">
          <template #default="{ row }">{{ configSummary(row) }}</template>
        </el-table-column>
        <el-table-column label="定时器" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.timerEnabled" size="small" type="success">
              {{ row.timerTrigger === "FY_END" ? "财年末" : "财年初" }}
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="sortOrder" label="排序" width="70" />
        <el-table-column label="展示" width="70">
          <template #default="{ row }">{{ row.visible !== false ? "是" : "否" }}</template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 产业字段详情（只读） -->
    <el-dialog
      append-to-body
      v-model="fieldDetailVisible"
      :title="`字段详情 · ${fieldDetailRow?.name || ''}`"
      width="620px"
    >
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="字段名称">{{ fieldDetailRow?.name || "—" }}</el-descriptions-item>
        <el-descriptions-item label="字段键">{{ fieldDetailRow?.fieldKey || "—" }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ fieldDetailRow?.fieldType || "—" }}</el-descriptions-item>
        <el-descriptions-item label="默认值">{{ fieldDetailRow?.defaultValue ?? "—" }}</el-descriptions-item>
        <el-descriptions-item label="是否计算字段">
          <el-tag v-if="fieldDetailRow?.isCalculated" size="small" type="warning">计算字段</el-tag>
          <span v-else>否</span>
        </el-descriptions-item>
        <el-descriptions-item label="计算配置">{{ formulaDisplay(fieldDetailRow) }}</el-descriptions-item>
        <el-descriptions-item label="排序">{{ fieldDetailRow?.sortOrder ?? 0 }}</el-descriptions-item>
        <el-descriptions-item label="前台展示">{{ fieldDetailRow?.visible !== false ? "是" : "否" }}</el-descriptions-item>
        <el-descriptions-item label="财年定时器">
          <template v-if="fieldDetailRow?.timerEnabled">
            <el-tag size="small" type="success">
              {{ fieldDetailRow?.timerTrigger === "FY_END" ? "财年末触发" : "财年初触发" }}
            </el-tag>
            <span style="margin-left: 6px"
              >设定值：{{
                (fieldDetailRow?.timerValue || "").startsWith("field:")
                  ? "引用字段 " + (fieldDetailRow?.timerValue || "").slice("field:".length)
                  : (fieldDetailRow?.timerValue ?? "—")
              }}</span
            >
          </template>
          <span v-else>否</span>
        </el-descriptions-item>
        <el-descriptions-item label="配置摘要">{{ configSummary(fieldDetailRow) }}</el-descriptions-item>
      </el-descriptions>
      <template v-if="fieldDetailRow?.isCalculated">
        <el-divider content-position="left">产业计算图（JSON）</el-divider>
        <pre class="detail-json">{{ fieldDetailRow?.calcGraph || "（空）" }}</pre>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive, watch, nextTick } from "vue";
import { useAuthStore } from "@/stores/auth";
import { industryTypesApi } from "@/api";
import { ElMessage, ElMessageBox } from "element-plus";
import IndustryFieldGraphEditor from "@/components/industry-types/IndustryFieldGraphEditor.vue";
import { useResourceChanged } from "@/realtime/useResourceChanged";
import { toPinyinKey } from "@/utils/pinyin";

const authStore = useAuthStore();

const loading = ref(false);
const saving = ref(false);
const types = ref<any[]>([]);
const searchText = ref("");
const showForm = ref(false);
const editingId = ref<number | null>(null);
const form = reactive<any>({ name: "", code: undefined, description: "" });

const showFields = ref(false);
const fieldTarget = ref<any>(null);
const fields = ref<any[]>([]);
const fieldLoading = ref(false);
const fieldSaving = ref(false);
const showGraphFullscreen = ref(false);
const typeDetailVisible = ref(false);
const typeDetailRow = ref<any>(null);
const fieldDetailVisible = ref(false);
const fieldDetailRow = ref<any>(null);
const fieldForm = reactive<any>({
  id: null,
  name: "",
  fieldKey: "",
  fieldType: "NUMBER",
  config: {},
  defaultValue: "",
  isCalculated: false,
  calcGraph: "",
  formula: "",
  editorMode: "formula" as "formula" | "graph",
  sortOrder: 0,
  visible: true,
  // 财年定时器
  timerEnabled: false,
  timerTrigger: "FY_START",
  timerValue: "",
});

const filteredTypes = computed(() => {
  const kw = searchText.value.trim().toLowerCase();
  if (!kw) return types.value;
  return types.value.filter(
    (t) => (t.name || "").toLowerCase().includes(kw) || String(t.code).includes(kw),
  );
});

async function loadTypes() {
  loading.value = true;
  try {
    const res: any = await industryTypesApi.list();
    types.value = Array.isArray(res) ? res : res?.items || res?.data || [];
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  } finally {
    loading.value = false;
  }
}

async function openCreate() {
  editingId.value = null;
  form.name = "";
  form.code = undefined;
  form.description = "";
  showForm.value = true;
}

function openEdit(row: any) {
  editingId.value = row.id;
  form.name = row.name;
  form.code = row.code;
  form.description = row.description || "";
  showForm.value = true;
}

async function submitForm() {
  if (!form.name.trim()) {
    ElMessage.warning("请填写产业名称");
    return;
  }
  saving.value = true;
  try {
    const payload: any = {
      name: form.name.trim(),
      description: form.description || undefined,
    };
    if (form.code !== undefined && form.code !== null) payload.code = form.code;
    if (editingId.value) {
      await industryTypesApi.update(editingId.value, payload);
      ElMessage.success("产业类型已更新");
    } else {
      await industryTypesApi.create(payload);
      ElMessage.success("产业类型已创建");
    }
    showForm.value = false;
    await loadTypes();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  } finally {
    saving.value = false;
  }
}

async function handleDelete(row: any) {
  try {
    await ElMessageBox.confirm(
      `确认删除产业类型「${row.name}」？其下的产业字段会一并删除，且不可恢复。`,
      "删除确认",
      { type: "warning", confirmButtonText: "确认删除" },
    );
    // 第二层确认（对标 CompetitionListView 的多层确认，产业类型降级为两层）
    await ElMessageBox.confirm(
      `再次确认：删除产业类型「${row.name}」后，其下所有产业字段及公司对应数值将一并清除，无法恢复。`,
      "二次确认",
      { type: "error", confirmButtonText: "我确定删除" },
    );
  } catch {
    return;
  }
  try {
    await industryTypesApi.remove(row.id);
    ElMessage.success("已删除");
    await loadTypes();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

// ============ 字段管理 ============

// 可作为计算公式引用的「其它字段」：本产业类型的字段，排除正在编辑的自身
const formulaFields = computed(() => {
  const selfKey = (fieldForm.fieldKey || "").trim();
  return (fields.value || [])
    .filter((f: any) => f.fieldKey !== selfKey)
    .map((f: any) => ({
      fieldKey: f.fieldKey,
      name: f.name,
      fieldType: f.fieldType,
      isCalculated: !!f.isCalculated,
      defaultValue: f.defaultValue,
    }));
});
const formulaTextareaRef = ref<HTMLTextAreaElement>();
function insertFormulaField(fieldKey: string) {
  const ta = formulaTextareaRef.value;
  if (!ta) {
    fieldForm.formula = (fieldForm.formula || "") + fieldKey;
    return;
  }
  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const val = fieldForm.formula || "";
  fieldForm.formula = val.slice(0, start) + fieldKey + val.slice(end);
  nextTick(() => {
    ta.focus();
    ta.selectionStart = ta.selectionEnd = start + fieldKey.length;
  });
}

// ===== 公式（Excel 风格）↔ calcGraph（单 FORMULA 节点）互转 =====
// 后端产业计算引擎原生支持 value(FORMULA) 节点，故把公式序列化为只含一个
// value(FORMULA)→output 的计算图，零后端改动即可复用既有级联重算能力。
function formulaToCalcGraph(expr: string): string {
  const g = {
    nodes: [
      { id: "out_1", type: "output", x: 60, y: 40, data: {} },
      { id: "val_1", type: "value", x: 320, y: 60, data: { kind: "FORMULA", expr } },
    ],
    edges: [
      { id: "e_1", source: "val_1", sourceHandle: "out", target: "out_1", targetHandle: "value" },
    ],
  };
  return JSON.stringify(g);
}

// 若 calcGraph 是「单 value(FORMULA)→output」的简单图，返回其公式表达式；否则返回 null（复杂图，需回退蓝图）。
function calcGraphToFormula(graphStr?: string | null): string | null {
  if (!graphStr) return null;
  try {
    const g = JSON.parse(graphStr);
    const nodes: any[] = Array.isArray(g?.nodes) ? g.nodes : [];
    const edges: any[] = Array.isArray(g?.edges) ? g.edges : [];
    if (nodes.length !== 2) return null;
    const out = nodes.find((n: any) => n.type === "output");
    const val = nodes.find((n: any) => n.type === "value" && n?.data?.kind === "FORMULA");
    if (!out || !val) return null;
    const linked = edges.some(
      (e: any) =>
        e.source === val.id && e.sourceHandle === "out" &&
        e.target === out.id && e.targetHandle === "value",
    );
    return linked ? (val?.data?.expr ?? "") : null;
  } catch {
    return null;
  }
}

// 财年定时器设定值输入框占位提示：因占位文案含双引号，抽出为计算属性避免在模板属性中截断。
const timerValuePlaceholder = computed(() =>
  fieldForm.fieldType === "DICTIONARY"
    ? 'JSON 对象，如 {"a":1,"b":2}'
    : 'JSON 数组，如 [1,2,3]',
);
// 财年定时器设定值来源：const=常量值；field=引用本产业字段
const timerValueMode = ref<"const" | "field">("const");
const timerValueRef = ref("");
// 可引用的候选字段：本产业内与当前字段「同类型、非自身、非计算字段」
const timerRefCandidates = computed(() =>
  (fields.value || []).filter(
    (f: any) =>
      f.fieldType === fieldForm.fieldType &&
      f.fieldKey !== fieldForm.fieldKey &&
      !f.isCalculated,
  ),
);
// 产业计算图由 IndustryFieldGraphEditor 以 v-model 编辑（fieldForm.calcGraph 为 JSON 字符串）。


// 不同字段类型的默认 config 结构
function defaultConfig(type: string): any {
  if (type === "DICTIONARY") return { entries: [], valueType: "NUMBER" };
  if (type === "LIST") return { itemType: "STRING" };
  return {};
}

function onFieldTypeChange(type: string) {
  // 切换类型时重置 config（用户手动切换，不会覆盖正在编辑的已有配置）
  fieldForm.config = defaultConfig(type);
  fieldForm.defaultValue = "";
}

function addDictEntry() {
  // 重建新数组再赋值：确保 setter 一定触发，v-for 依赖必定重渲染（避免任何响应式追踪丢失）
  const arr = Array.isArray(fieldForm.config.entries) ? [...fieldForm.config.entries] : [];
  arr.push({ key: "", label: "", defaultValue: "" });
  fieldForm.config.entries = arr;
}
function removeDictEntry(idx: number) {
  fieldForm.config.entries.splice(idx, 1);
}

// 克隆并规整后端返回的 config，便于表单编辑
function cloneConfig(type: string, raw: any): any {
  const cfg = raw || {};
  if (type === "DICTIONARY")
    return {
      entries: Array.isArray(cfg.entries)
        ? cfg.entries.map((e: any) => ({
            key: e.key ?? "",
            label: e.label ?? "",
            defaultValue: e.defaultValue ?? "",
          }))
        : [],
      valueType: cfg.valueType || "NUMBER",
    };
  if (type === "LIST") return { itemType: cfg.itemType || "STRING" };
  return {};
}

// 字段配置的简要展示
function configSummary(f: any): string {
  const t = f.fieldType;
  const cfg = f.config || {};
  if (t === "DICTIONARY") {
    const entries = Array.isArray(cfg.entries) ? cfg.entries : [];
    const names = entries.map((e: any) => e.label || e.key).join("、");
    return `字典(${cfg.valueType || "NUMBER"}): ${names || "（未定义项）"}`;
  }
  if (t === "LIST") return `列表(${cfg.itemType || "STRING"})`;
  return "—";
}

// 规则列展示：计算字段显示公式表达式（简单图）或蓝图摘要（复杂图），普通字段显示原始公式
function formulaDisplay(f: any): string {
  if (!f.isCalculated) return f.formula || "—";
  const expr = calcGraphToFormula(f.calcGraph);
  if (expr !== null) return expr || "（空公式）";
  try {
    const g = JSON.parse(f.calcGraph || "{}");
    const n = Array.isArray(g.nodes) ? g.nodes.length : 0;
    return `可视化蓝图 (${n} 节点)`;
  } catch {
    return "可视化蓝图";
  }
}

// 自动生成唯一字段键：字段名拼音 + 冲突时追加序号，保证产业类型内唯一
function generateFieldKey(): string {
  const base = toPinyinKey((fieldForm.name || "").trim()) || "field";
  const used = new Set((fields.value || []).map((f: any) => f.fieldKey));
  let key = base;
  let i = 1;
  while (used.has(key)) {
    key = `${base}_${i}`;
    i++;
  }
  return key;
}

// 新建字段：输入字段名时实时用拼音自动生成字段键（编辑态字段键只读，不覆盖）
watch(
  () => fieldForm.name,
  () => {
    if (!fieldForm.id) {
      fieldForm.fieldKey = (fieldForm.name || "").trim() ? generateFieldKey() : "";
    }
  },
);

function resetFieldForm() {
  fieldForm.id = null;
  fieldForm.name = "";
  fieldForm.fieldKey = "";
  fieldForm.fieldType = "NUMBER";
  fieldForm.config = {};
  fieldForm.defaultValue = "";
  fieldForm.isCalculated = false;
  fieldForm.calcGraph = "";
  fieldForm.formula = "";
  fieldForm.editorMode = "formula";
  fieldForm.sortOrder = 0;
  fieldForm.visible = true;
  fieldForm.timerEnabled = false;
  fieldForm.timerTrigger = "FY_START";
  fieldForm.timerValue = "";
  timerValueMode.value = "const";
  timerValueRef.value = "";
}

async function openFields(row: any) {
  fieldTarget.value = row;
  resetFieldForm();
  showFields.value = true;
  await loadFields();
}

async function loadFields() {
  if (!fieldTarget.value) return;
  fieldLoading.value = true;
  try {
    const res: any = await industryTypesApi.listFields(fieldTarget.value.id);
    fields.value = Array.isArray(res) ? res : res?.items || res?.data || [];
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  } finally {
    fieldLoading.value = false;
  }
}

function editField(row: any) {
  fieldForm.id = row.id;
  fieldForm.name = row.name;
  fieldForm.fieldKey = row.fieldKey;
  fieldForm.fieldType = row.fieldType;
  fieldForm.config = cloneConfig(row.fieldType, row.config);
  fieldForm.defaultValue = row.defaultValue || "";
  fieldForm.isCalculated = !!row.isCalculated;
  fieldForm.calcGraph = row.calcGraph || "";
  fieldForm.formula = "";
  fieldForm.editorMode = "formula";
  fieldForm.sortOrder = row.sortOrder || 0;
  fieldForm.visible = row.visible !== false;
  fieldForm.timerEnabled = !!row.timerEnabled;
  fieldForm.timerTrigger = row.timerTrigger || "FY_START";
  if (typeof row.timerValue === "string" && row.timerValue.startsWith("field:")) {
    timerValueMode.value = "field";
    timerValueRef.value = row.timerValue.slice("field:".length);
    fieldForm.timerValue = "";
  } else {
    timerValueMode.value = "const";
    timerValueRef.value = "";
    fieldForm.timerValue = row.timerValue || "";
  }
}

// 计算字段：进入全屏编辑器。默认「公式」模式；若已有计算图是「单 FORMULA 节点」简单图，
// 则把公式回填到公式框；若是复杂图（含 OP / IF / CONSUMER_DEMAND 等），回退「蓝图(高级)」模式保留可编辑性；
// 全新计算字段（无计算图）也默认「公式」模式。
function openGraphFullscreen(row: any) {
  editField(row);
  if (row.isCalculated) {
    const hasGraph = !!(row.calcGraph && row.calcGraph.trim());
    if (!hasGraph) {
      fieldForm.formula = "";
      fieldForm.editorMode = "formula";
    } else {
      const f = calcGraphToFormula(row.calcGraph);
      if (f !== null) {
        fieldForm.formula = f;
        fieldForm.editorMode = "formula";
      } else {
        fieldForm.editorMode = "graph";
      }
    }
  }
  showGraphFullscreen.value = true;
}

// 切换编辑模式时同步两种表示：公式↔calcGraph，避免来回切换丢失已编辑内容。
function onEditorModeChange(mode: "formula" | "graph") {
  if (mode === "formula") {
    const f = calcGraphToFormula(fieldForm.calcGraph);
    if (f !== null) fieldForm.formula = f;
  } else if (mode === "graph") {
    if (!fieldForm.calcGraph?.trim() && fieldForm.formula?.trim()) {
      fieldForm.calcGraph = formulaToCalcGraph(fieldForm.formula.trim());
    }
  }
}

// 只读详情：产业类型（含其字段列表），无管理权限也可查看
function openTypeDetail(row: any) {
  typeDetailRow.value = row;
  typeDetailVisible.value = true;
}

// 只读详情：单个产业字段
function openFieldDetail(row: any) {
  fieldDetailRow.value = row;
  fieldDetailVisible.value = true;
}

async function submitField() {
  if (!fieldForm.name.trim()) {
    ElMessage.warning("请填写字段名称");
    return;
  }
  // 字段键兜底：新建时若尚未自动生成，按名称拼音生成
  if (!fieldForm.fieldKey.trim()) {
    fieldForm.fieldKey = generateFieldKey();
  }
  // 计算字段：公式模式下把 Excel 风格公式序列化为 calcGraph（单 FORMULA 节点）
  if (fieldForm.isCalculated && fieldForm.editorMode === "formula") {
    if (!fieldForm.formula?.trim()) {
      ElMessage.warning("计算字段必须填写公式（Excel 风格，可用其它字段键作变量）");
      return;
    }
    fieldForm.calcGraph = formulaToCalcGraph(fieldForm.formula.trim());
  }
  if (fieldForm.isCalculated && !fieldForm.calcGraph?.trim()) {
    ElMessage.warning("计算字段必须配置产业计算图（可视化蓝图）");
    return;
  }
  // 财年定时器校验：启用且非计算字段时，必须选择触发时机并填写设定值
  if (fieldForm.timerEnabled && !fieldForm.isCalculated) {
    if (!fieldForm.timerTrigger) {
      ElMessage.warning("请选择财年定时器的触发时机");
      return;
    }
    if (timerValueMode.value === "field") {
      if (!timerValueRef.value) {
        ElMessage.warning("请选择要引用的本产业字段");
        return;
      }
    } else if (
      fieldForm.fieldType === "BOOLEAN"
        ? fieldForm.timerValue !== "true" && fieldForm.timerValue !== "false"
        : !String(fieldForm.timerValue ?? "").trim()
    ) {
      ElMessage.warning("请填写财年定时器触发后写入的设定值");
      return;
    }
  }
  // 计算字段：校验产业计算图（恰好一个「输出」节点）
  if (fieldForm.isCalculated) {
    try {
      const g = JSON.parse(fieldForm.calcGraph || "{}");
      const nodes = Array.isArray(g.nodes) ? g.nodes : [];
      const outs = nodes.filter((n: any) => n.type === "output");
      if (outs.length !== 1) {
        ElMessage.warning("产业计算图必须且只能有一个「输出」节点");
        return;
      }
    } catch {
      ElMessage.warning("产业计算图 JSON 解析失败，请检查后重试");
      return;
    }
  }
  // 构建并校验 config
  let config: any = defaultConfig(fieldForm.fieldType);
  if (fieldForm.fieldType === "DICTIONARY") {
    const entries = (fieldForm.config.entries || [])
      .filter((e: any) => (e.key || "").trim() && (e.label || "").trim())
      .map((e: any) => ({
        key: e.key.trim(),
        label: e.label.trim(),
        defaultValue: e.defaultValue ?? "",
      }));
    // 允许创建空字典字段（不强制至少一个字典项）；有填的项仍做清洗校验
    config = { valueType: fieldForm.config.valueType || "NUMBER", entries };
  } else if (fieldForm.fieldType === "LIST") {
    config = { itemType: fieldForm.config.itemType || "STRING" };
  }
  fieldSaving.value = true;
  try {
    const payload: any = {
      name: fieldForm.name.trim(),
      fieldKey: fieldForm.fieldKey.trim(),
      fieldType: fieldForm.fieldType,
      config,
      defaultValue: fieldForm.defaultValue || undefined,
      isCalculated: fieldForm.isCalculated,
      calcGraph: fieldForm.isCalculated ? fieldForm.calcGraph : null,
      formula: null,
      sortOrder: fieldForm.sortOrder ?? 0,
      visible: fieldForm.visible !== false,
      // 财年定时器：启用且非计算字段时落库触发时机与设定值；否则清空三列。
      // 引用模式下 timerValue 存为 `field:<字段键>`；常量模式存字面量。
      timerEnabled: fieldForm.timerEnabled && !fieldForm.isCalculated,
      timerTrigger:
        fieldForm.timerEnabled && !fieldForm.isCalculated ? fieldForm.timerTrigger : null,
      timerValue: (() => {
        if (!(fieldForm.timerEnabled && !fieldForm.isCalculated)) return null;
        return timerValueMode.value === "field"
          ? "field:" + (timerValueRef.value || "")
          : fieldForm.timerValue || null;
      })(),
    };
    if (fieldForm.id) {
      await industryTypesApi.updateField(fieldForm.id, payload);
      ElMessage.success("字段已更新");
    } else {
      await industryTypesApi.createField(fieldTarget.value.id, payload);
      ElMessage.success("字段已添加");
    }
    showGraphFullscreen.value = false;
    resetFieldForm();
    await loadFields();
    await loadTypes();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  } finally {
    fieldSaving.value = false;
  }
}

async function deleteField(row: any) {
  try {
    await ElMessageBox.confirm(
      `确认删除字段「${row.name}」？公司中该字段已录入的数值会一并删除。`,
      "删除确认",
      { type: "warning" },
    );
  } catch {
    return;
  }
  try {
    await industryTypesApi.removeField(row.id);
    ElMessage.success("已删除");
    await loadFields();
    await loadTypes();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

// 即时切换字段的前台展示开关：隐藏字段不在任何客户端界面显示（公司管理 / 区域总览 / 合同编辑器等）
async function toggleFieldVisible(row: any, val: any) {
  const next = !!val;
  try {
    await industryTypesApi.updateField(row.id, { visible: next });
    row.visible = next;
    ElMessage.success(next ? "字段已设为展示" : "字段已隐藏");
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

onMounted(async () => {
  await loadTypes();
});

useResourceChanged("industry-types", () => {
  loadTypes();
}, { scope: "global" });
</script>

<style scoped>
.it-manager {
  width: 100%;
}
.toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.expand-fields {
  padding: 10px 20px;
}
.empty-tip {
  color: #909399;
  font-size: 13px;
  padding: 6px 0;
}
.empty-tip {
  color: #909399;
  font-size: 13px;
  padding: 6px 0;
}
.hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}
.dict-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}
.ge-host {
  width: 100%;
  height: 520px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
}
.fb-wrap {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.fb-readout {
  flex: 1;
  min-width: 280px;
}
.fb-readout-title {
  font-size: 12px;
  color: #606266;
  margin: 4px 0;
}
.fb-json {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
.fb-text {
  background: #f4f4f5;
  color: #303133;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
}
.detail-json {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
/* ===== 全屏蓝图编辑器 ===== */
.fs-dialog {
  display: flex;
  flex-direction: column;
  background: #f5f6fa;
  padding: 0;
  overflow: hidden;
}
.fs-dialog :deep(.el-dialog__header) {
  display: none;
}
.fs-dialog :deep(.el-dialog__body) {
  position: relative;
  height: 100%;
  flex: 1;
  padding: 0;
  overflow: hidden;
  display: flex;
}
.fs-wrap {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  width: 100%;
}
.fs-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}
.fs-title {
  display: flex;
  align-items: center;
  gap: 10px;
}
.fs-title-main {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.fs-actions {
  display: flex;
  gap: 10px;
}
.fs-main {
  flex: 1;
  display: flex;
  position: relative;
  min-height: 0;
}
.fs-details {
  flex: 0 0 280px;
  align-self: flex-start;
  width: 280px;
  max-height: 100%;
  overflow: auto;
  padding: 14px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
}
.fs-details-title {
  font-weight: bold;
  margin-bottom: 10px;
  color: #303133;
  font-size: 14px;
}
.fs-details-form {
  margin-bottom: 0;
}
.fs-editor {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  position: relative;
}
.fs-mode-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  flex-wrap: wrap;
}
.fs-mode-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}
.fs-mode-tip code {
  background: #f4f4f5;
  padding: 0 4px;
  border-radius: 3px;
  font-family: monospace;
  color: #409eff;
}
.fs-formula {
  padding: 14px;
  height: calc(100% - 52px);
  overflow: auto;
}
.fs-formula-wrapper {
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.fs-formula-fields {
  padding: 10px 12px;
  border-bottom: 1px solid #e0e0e0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.fs-formula-fields-title {
  font-size: 12px;
  font-weight: 500;
  color: #8c8c8c;
}
.fs-formula-field-key {
  display: inline-block;
  background: #ecf5ff;
  color: #409eff;
  border: 1px solid #d9ecff;
  border-radius: 3px;
  padding: 2px 6px;
  font-size: 11px;
  font-family: monospace;
  cursor: pointer;
  transition: all 0.15s;
}
.fs-formula-field-key:hover {
  background: #d9ecff;
  border-color: #409eff;
}
.fs-formula-textarea {
  width: 100%;
  min-height: 100px;
  padding: 10px 12px;
  font-family: "Cascadia Code", "Fira Code", "Consolas", "Courier New", monospace;
  font-size: 13px;
  line-height: 1.5;
  border: none;
  outline: none;
  resize: vertical;
  background: #fafbfc;
  color: #303133;
  box-sizing: border-box;
}
.fs-formula-textarea:focus {
  background: #fff;
}
</style>
