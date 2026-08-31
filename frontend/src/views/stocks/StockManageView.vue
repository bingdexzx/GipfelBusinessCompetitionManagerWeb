<template>
  <div class="stock-manage">
    <div class="mm-toolbar">
      <h2 class="mm-title">股票管理</h2>
      <div class="mm-actions">
        <el-button :icon="Refresh" @click="reloadAll">刷新</el-button>
      </div>
    </div>

    <!-- 股票管理（仅高级管理） -->
    <el-card v-if="canManage" shadow="never" class="block-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">股票（{{ stocks.length }}）</span>
          <div class="card-actions">
            <el-button type="primary" :icon="Plus" @click="openStockDialog()">新增股票</el-button>
            <el-button type="warning" :icon="VideoPlay" @click="openAdvanceDialog">推进一轮</el-button>
          </div>
        </div>
      </template>
      <el-table :data="stocks" size="small" v-loading="loadingStocks">
        <el-table-column prop="code" label="代码" width="90" />
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column label="当前价" min-width="95" align="right">
          <template #default="{ row }">{{ fmt(row.currentPrice) }}</template>
        </el-table-column>
        <el-table-column label="初始价" min-width="95" align="right">
          <template #default="{ row }">{{ fmt(row.initPrice) }}</template>
        </el-table-column>
        <el-table-column prop="round" label="轮次" width="64" align="center" />
        <el-table-column prop="totalShares" label="总股本(万)" min-width="100" align="right" />
        <el-table-column label="有效PE" min-width="110" align="right">
          <template #default="{ row }">
            <span>{{ fmt(row.effectivePb ?? row.industryPE) }}</span>
            <el-tag v-if="row.pbMode === 'linked'" size="small" type="success" effect="plain" class="bind-tag">联动</el-tag>
            <el-tag v-else size="small" type="info" effect="plain" class="bind-tag">随机</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="幸福度" min-width="95" align="right">
          <template #default="{ row }">
            <span>{{ fmt(row.effectiveHappiness ?? row.happiness) }}</span>
            <el-tag v-if="row.happinessFieldRef" size="small" type="success" effect="plain" class="bind-tag">联动</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="碳排" min-width="95" align="right">
          <template #default="{ row }">
            <span>{{ fmt(row.effectiveCurrentCarbon ?? row.currentCarbon) }}</span>
            <el-tag v-if="row.carbonFieldRef" size="small" type="success" effect="plain" class="bind-tag">联动</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="行业碳排均值" min-width="120" align="right">
          <template #default="{ row }">
            <span>{{ fmt(row.effectiveIndustryAvgCarbon ?? row.industryAvgCarbon) }}</span>
            <el-tag v-if="row.industryAvgCarbonRefs" size="small" type="success" effect="plain" class="bind-tag">联动</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text @click="openStockDialog(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="removeStock(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 资金账户管理（低级 / 高级） -->
    <el-card v-if="canEdit" shadow="never" class="block-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">资金账户（{{ accounts.length }}）</span>
          <el-button type="primary" :icon="Plus" @click="openAccountDialog()">新增账户</el-button>
        </div>
      </template>
      <el-table :data="accounts" size="small" v-loading="loadingAccounts">
        <el-table-column prop="name" label="账户名" min-width="120" />
        <el-table-column label="类型" width="80">
          <template #default="{ row }">{{ row.ownerType === "USER" ? "个人" : "公司" }}</template>
        </el-table-column>
        <el-table-column label="归属" min-width="120">
          <template #default="{ row }">
            <span v-if="row.ownerType === 'USER'">{{ row.userId === authStore.user?.id ? "我自己" : "用户#" + row.userId }}</span>
            <span v-else>{{ companyName(row.companyId) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="现金(元)" width="160" align="right">
          <template #default="{ row }">
            <template v-if="row.bindFieldId">
              {{ fmt(row.fieldBalance != null ? row.fieldBalance : row.cashBalance) }}
              <el-tag size="small" type="success" effect="plain" class="field-link-tag">联动</el-tag>
            </template>
            <span v-else>{{ fmt(row.cashBalance) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text @click="openAccountDialog(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="removeAccount(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 账户总览（仅超级管理员） -->
    <el-card v-if="canSuper" shadow="never" class="block-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">账户总览（{{ overview.length }}）</span>
          <el-button type="primary" :icon="Refresh" @click="reloadOverview">刷新总览</el-button>
        </div>
      </template>
      <el-table :data="overview" size="small" v-loading="loadingOverview" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="holding-detail" v-if="row.holdings && row.holdings.length">
              <table class="holding-table">
                <thead>
                  <tr>
                    <th>代码</th><th>名称</th><th class="num">股数</th><th class="num">成本价</th>
                    <th class="num">现价</th><th class="num">市值</th><th class="num">成本</th>
                    <th class="num">盈亏</th><th class="num">盈亏率</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="h in row.holdings" :key="h.stockCode">
                    <td>{{ h.stockCode }}</td>
                    <td>{{ h.stockName }}</td>
                    <td class="num">{{ fmt(h.shares) }}</td>
                    <td class="num">{{ fmt(h.costPrice) }}</td>
                    <td class="num">{{ fmt(h.currentPrice) }}</td>
                    <td class="num">{{ fmt(h.marketValue) }}</td>
                    <td class="num">{{ fmt(h.costBasis) }}</td>
                    <td class="num" :class="h.profit >= 0 ? 'up' : 'down'">{{ fmt(h.profit) }}</td>
                    <td class="num" :class="h.profitPct >= 0 ? 'up' : 'down'">{{ h.profitPct }}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <el-empty v-else description="无持仓" :image-size="40" />
          </template>
        </el-table-column>
        <el-table-column prop="name" label="账户名" min-width="120" />
        <el-table-column label="类型" width="70">
          <template #default="{ row }">{{ row.ownerLabel }}</template>
        </el-table-column>
        <el-table-column label="归属" min-width="120">
          <template #default="{ row }">
            <span v-if="row.ownerType === 'USER'">用户#{{ row.userId }}</span>
            <span v-else>{{ row.companyName || ("公司#" + row.companyId) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="可用资金(元)" min-width="130" align="right">
          <template #default="{ row }">{{ fmt(row.cashBalance) }}</template>
        </el-table-column>
        <el-table-column label="持仓市值(元)" min-width="130" align="right">
          <template #default="{ row }">{{ fmt(row.holdingsMarketValue) }}</template>
        </el-table-column>
        <el-table-column label="总资产(元)" min-width="130" align="right">
          <template #default="{ row }">{{ fmt(row.totalAssets) }}</template>
        </el-table-column>
        <el-table-column label="历史盈亏(元)" min-width="130" align="right">
          <template #default="{ row }">
            <span :class="row.totalProfit >= 0 ? 'up' : 'down'">{{ fmt(row.totalProfit) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="盈亏率" min-width="90" align="right">
          <template #default="{ row }">
            <span :class="row.totalProfitPct >= 0 ? 'up' : 'down'">{{ row.totalProfitPct }}%</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 股票编辑对话框 -->
    <el-dialog append-to-body v-model="stockDialogVisible" :title="stockForm.id ? '编辑股票' : '新增股票'" width="560px">
      <el-form :model="stockForm" label-width="110px" size="small">
        <el-form-item label="股票代码" required>
          <el-input v-model="stockForm.code" :disabled="!!stockForm.id" placeholder="如 600001" />
        </el-form-item>
        <el-form-item label="股票名称" required>
          <el-input v-model="stockForm.name" />
        </el-form-item>
        <el-form-item label="总股本(万股)" required>
          <el-input-number v-model="stockForm.totalShares" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="初始净利润(万)" required>
          <el-input-number v-model="stockForm.initNetProfit" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="PE 关联公司">
          <el-select
            v-model="stockForm.pbCompanyId"
            placeholder="不选择 = 随机源模式"
            clearable
            style="width: 100%"
            @change="onPbCompanyChange"
          >
            <el-option v-for="c in pbCompanies" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="stockForm.pbCompanyId" label="PE 绑定字段" required>
          <el-select v-model="stockForm.pbFieldId" placeholder="选择该公司的数值型产业字段" clearable style="width: 100%">
            <el-option v-for="f in pbFieldsForSelectedCompany" :key="f.id" :label="(f.name || f.fieldKey) + '（' + f.fieldType + '）'" :value="f.id" />
          </el-select>
        </el-form-item>
        <div v-if="!stockForm.pbCompanyId" class="pb-hint muted">
          随机模式：未选择关联公司时，PE 在 0~20 间随机生成，每推进一轮按 ±2 步长随机游走。
        </div>
        <el-form-item label="碳排绑定字段">
          <el-select v-model="stockForm.carbonRefSel" placeholder="不绑定（手动输入）" clearable style="width: 100%">
            <el-option label="不绑定（手动输入）" value="" />
            <el-option v-for="c in regionCards" :key="c.key" :label="c.label" :value="c.key" :disabled="!c.valid" />
          </el-select>
        </el-form-item>
        <el-form-item label="当前碳排" required>
          <div v-if="carbonBound" class="bound-value">
            <span class="bound-num">{{ carbonLiveText }}</span>
            <span class="muted">（实时引用「{{ carbonBoundLabel }}」）</span>
          </div>
          <el-input-number v-else v-model="stockForm.currentCarbon" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="行业碳排均值绑定字段">
          <el-select
            v-model="stockForm.industryAvgCarbonRefsSel"
            multiple
            filterable
            placeholder="不绑定（手动输入），可多选取平均值"
            clearable
            style="width: 100%"
          >
            <el-option v-for="c in regionCards" :key="c.key" :label="c.label" :value="c.key" :disabled="!c.valid" />
          </el-select>
        </el-form-item>
        <el-form-item label="行业碳排均值" required>
          <div v-if="industryAvgCarbonBound" class="bound-value">
            <span class="bound-num">{{ industryAvgCarbonLiveText }}</span>
            <span class="muted">（实时引用 {{ stockForm.industryAvgCarbonRefsSel.length }} 个字段的平均值）</span>
          </div>
          <el-input-number v-else v-model="stockForm.industryAvgCarbon" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="幸福度绑定字段">
          <el-select v-model="stockForm.happinessRefSel" placeholder="不绑定（手动输入）" clearable style="width: 100%">
            <el-option label="不绑定（手动输入）" value="" />
            <el-option v-for="c in regionCards" :key="c.key" :label="c.label" :value="c.key" :disabled="!c.valid" />
          </el-select>
        </el-form-item>
        <el-form-item label="当前幸福度" required>
          <div v-if="happinessBound" class="bound-value">
            <span class="bound-num">{{ happinessLiveText }}</span>
            <span class="muted">（实时引用「{{ happinessBoundLabel }}」）</span>
          </div>
          <el-input-number v-else v-model="stockForm.happiness" :min="0" :max="100" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          title="初始价由系统按「净利润×10000 / 总股本 / 有效PE」自动计算，无需手动填写。"
        />
      </el-form>
      <template #footer>
        <el-button @click="stockDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveStock">保存</el-button>
      </template>
    </el-dialog>

    <!-- 资金账户编辑对话框 -->
    <el-dialog append-to-body v-model="accountDialogVisible" :title="accountForm.id ? '编辑账户' : '新增资金账户'" width="520px">
      <el-form :model="accountForm" label-width="100px" size="small">
        <el-form-item label="账户名" required>
          <el-input v-model="accountForm.name" :disabled="!!accountForm.id" />
        </el-form-item>
        <el-form-item label="账户类型" required>
          <el-radio-group v-model="accountForm.ownerType" :disabled="!!accountForm.id" @change="onAccountTypeChange">
            <el-radio-button value="USER">个人</el-radio-button>
            <el-radio-button value="COMPANY">公司</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="accountForm.ownerType === 'COMPANY'" label="归属公司" required>
          <el-select v-model="accountForm.companyId" placeholder="选择公司" style="width: 100%" @change="onAccountCompanyChange">
            <el-option v-for="c in scopedCompanies" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="accountForm.ownerType === 'COMPANY' && accountForm.companyId" label="绑定字段">
          <el-select v-model="accountForm.bindFieldId" placeholder="选择产业字段（可选）" clearable style="width: 100%" @change="onAccountFieldChange">
            <el-option label="不绑定（手动输入）" :value="null" />
            <el-option v-for="f in accountFieldsForCompany" :key="f.id" :label="(f.name || f.fieldKey) + '（' + f.fieldType + '）'" :value="f.id" />
          </el-select>
          <div v-if="accountForm.bindFieldId && accountBoundFieldValue != null" class="field-hint">
            字段当前值：<b>{{ fmt(accountBoundFieldValue) }}</b>
          </div>
        </el-form-item>
        <el-form-item v-if="accountForm.ownerType === 'USER'" label="归属用户">
          <span class="muted">{{ authStore.user?.displayName || authStore.user?.username || "我自己" }}</span>
        </el-form-item>
        <el-form-item v-if="accountForm.manualCash" label="初始现金(元)">
          <el-input-number v-model="accountForm.cashBalance" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-alert v-if="accountForm.ownerType === 'USER'" type="info" :closable="false" title="个人账户初始资金固定为 100 万元。" />
        <el-alert v-if="accountForm.bindFieldId" type="info" :closable="false" title="已绑定产业字段，资金余额将自动同步字段值，交易时直接加减该字段。" />
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveAccount">保存</el-button>
      </template>
    </el-dialog>

    <!-- 做市商配置对话框 -->
    <el-dialog append-to-body v-model="mmDialogVisible" title="推进轮次 — AI 做市商配置" width="520px">
      <el-alert
        type="info"
        :closable="false"
        title="AI 做市商将在每轮撮合前自动挂单，为市场提供流动性（买卖盘深度）。"
        style="margin-bottom: 16px;"
      />
      <el-form :model="mmConfig" label-width="120px" size="small">
        <el-form-item label="启用做市商">
          <el-switch v-model="mmConfig.enabled" />
          <span class="muted" style="margin-left: 8px;">关闭后仅撮合玩家挂单</span>
        </el-form-item>
        <template v-if="mmConfig.enabled">
          <el-form-item label="点差百分比">
            <el-input-number v-model="mmConfig.spreadPct" :min="0.1" :max="20" :step="0.5" :precision="1" style="width: 100%" />
            <div class="form-hint">每档价格偏离当前价的百分比（如 2 表示 ±2%）</div>
          </el-form-item>
          <el-form-item label="挂单档数">
            <el-input-number v-model="mmConfig.levels" :min="1" :max="10" :step="1" style="width: 100%" />
            <div class="form-hint">买卖各挂 N 档，形成盘口深度</div>
          </el-form-item>
          <el-form-item label="每档基础数量">
            <el-input-number v-model="mmConfig.baseQuantity" :min="100" :max="100000" :step="100" style="width: 100%" />
            <div class="form-hint">每档挂单量（越远档越多：第 N 档 = 基础量 × N）</div>
          </el-form-item>
          <el-alert
            type="warning"
            :closable="false"
            :title="`预览：以当前价 ¥100 为例，做市商将挂 ${mmConfig.levels * 2} 笔订单（买卖各 ${mmConfig.levels} 档），点差 ${mmConfig.spreadPct}%`"
          />
        </template>
        <el-divider content-position="left">股票引擎参数（高级 · 覆盖比赛默认配置 S8）</el-divider>
        <el-form-item label="涨跌停限幅">
          <el-input-number v-model="stockConfigForm.limitPct" :min="0.02" :max="0.5" :step="0.01" :precision="2" style="width: 100%" />
          <div class="form-hint">单日硬限幅（比例，如 0.10 = ±10%）</div>
        </el-form-item>
        <el-form-item label="单轮最大波动">
          <el-input-number v-model="stockConfigForm.maxMovePct" :min="0.001" :max="0.2" :step="0.005" :precision="3" style="width: 100%" />
          <div class="form-hint">相对买卖净压力的最大移动（默认 0.05 = 5%，避免一字封板）</div>
        </el-form-item>
        <el-form-item label="连续封板干预">
          <el-select v-model="stockConfigForm.interventionMode" style="width: 100%">
            <el-option label="回归锚（温和拉回）" value="regression" />
            <el-option label="扩板（放宽限幅）" value="expand-limit" />
          </el-select>
        </el-form-item>
        <el-form-item label="回归锚偏移" v-if="stockConfigForm.interventionMode === 'regression'">
          <el-input-number v-model="stockConfigForm.regressionPct" :min="0" :max="0.1" :step="0.005" :precision="3" style="width: 100%" />
          <div class="form-hint">干预挂单价相对上轮收盘的偏移（默认 0.02 = 2%）</div>
        </el-form-item>
        <el-form-item label="成交价权重">
          <el-input-number v-model="stockConfigForm.tradePriceWeight" :min="0" :max="1" :step="0.05" :precision="2" style="width: 100%" />
          <div class="form-hint">最终价中成交价的占比（默认 0.7），其余为理论价（S5）</div>
        </el-form-item>
        <el-form-item label="幸福度偏置">
          <el-input-number v-model="stockConfigForm.happinessImpact" :min="0" :max="1" :step="0.05" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="碳排偏置">
          <el-input-number v-model="stockConfigForm.carbonImpact" :min="0" :max="1" :step="0.05" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="碳排对数锚点 R">
          <el-input-number v-model="stockConfigForm.carbonSaturateRatio" :min="1.1" :max="20" :step="0.5" :precision="2" style="width: 100%" />
          <div class="form-hint">碳排=R 倍行业均值时偏置达 -1；之后随碳排对数持续更负（不再早饱和，默认 2）</div>
        </el-form-item>
        <el-form-item label="做市商深度占比">
          <el-input-number v-model="stockConfigForm.mmDepthPct" :min="0" :max="0.05" :step="0.0005" :precision="4" style="width: 100%" />
          <div class="form-hint">单档深度占总股本比例（默认 0.001，深度随股本动态化 S3）</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="mmDialogVisible = false">取消</el-button>
        <el-button type="warning" :icon="VideoPlay" @click="confirmAdvance">确认推进</el-button>
      </template>
    </el-dialog>

    <!-- S9：本轮定价诊断面板，运营可直接看到「为什么本轮涨/跌/封板」 -->
    <el-dialog append-to-body v-model="diagVisible" title="本轮定价诊断（S9）" width="760px">
      <el-table :data="advanceResults" size="small" max-height="440" stripe>
        <el-table-column prop="code" label="代码" width="92" />
        <el-table-column label="状态" width="78">
          <template #default="{ row }">
            <el-tag v-if="row.skipped" type="info" size="small">跳过</el-tag>
            <el-tag v-else type="success" size="small">已推进</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="成交" width="64">
          <template #default="{ row }">{{ row.matched ? "是" : "否" }}</template>
        </el-table-column>
        <el-table-column label="净买压力" width="96">
          <template #default="{ row }">{{ fmtNum(row.pressure) }}</template>
        </el-table-column>
        <el-table-column label="趋势偏置" width="96">
          <template #default="{ row }">{{ fmtNum(row.drift) }}</template>
        </el-table-column>
        <el-table-column label="理论价" width="88">
          <template #default="{ row }">{{ fmtNum(row.theoretical, 2) }}</template>
        </el-table-column>
        <el-table-column label="最终价" width="88">
          <template #default="{ row }">{{ fmtNum(row.finalPrice, 2) }}</template>
        </el-table-column>
        <el-table-column label="干预" width="64">
          <template #default="{ row }">
            <el-tag v-if="row.mmIntervened" type="warning" size="small">是</el-tag>
            <span v-else>否</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button type="primary" @click="diagVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from "vue";
import { Plus, Refresh, VideoPlay } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { stockApi, companiesApi, regionsApi, companyFieldsApi } from "@/api";
import { useCompetitionStore } from "@/stores/competition";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";
import { formatMoney } from "@/utils/format";

const compStore = useCompetitionStore();
const authStore = useAuthStore();
const canManage = computed(() => authStore.can("stock:manage"));
const canEdit = computed(() => authStore.canAny(["stock:edit", "stock:manage"]));
// 账户总览：仅超级管理员可见
const canSuper = computed(() => authStore.user?.role === "SUPER_ADMIN");

interface Stock {
  id: number;
  code: string;
  name: string;
  currentPrice: number;
  initPrice: number;
  round: number;
  totalShares: number;
  industryPE: number;
  happiness: number;
  currentCarbon: number;
  carbonFieldRef?: string | null;
  happinessFieldRef?: string | null;
  effectiveCurrentCarbon?: number;
  effectiveHappiness?: number;
}
interface Account {
  id: number;
  name: string;
  ownerType: string;
  companyId: number | null;
  userId: number | null;
  cashBalance: number;
}
interface Company {
  id: number;
  name: string;
}

const stocks = ref<Stock[]>([]);
const accounts = ref<Account[]>([]);
const companies = ref<Company[]>([]);
const loadingStocks = ref(false);
const loadingAccounts = ref(false);

// 账户总览（仅超级管理员）
interface OverviewHolding {
  stockCode: string;
  stockName: string;
  shares: number;
  costPrice: number;
  currentPrice: number;
  marketValue: number;
  costBasis: number;
  profit: number;
  profitPct: number;
}
interface AccountOverview {
  id: number;
  name: string;
  ownerType: string;
  ownerLabel: string;
  companyId: number | null;
  companyName: string | null;
  userId: number | null;
  cashBalance: number;
  holdings: OverviewHolding[];
  holdingsMarketValue: number;
  costBasis: number;
  totalAssets: number;
  totalProfit: number;
  totalProfitPct: number;
}
const overview = ref<AccountOverview[]>([]);
const loadingOverview = ref(false);

const stockDialogVisible = ref(false);
const stockForm = ref<any>({ code: "", name: "", totalShares: 0, initNetProfit: 0, currentCarbon: 0, industryAvgCarbon: 0, happiness: 50, companyId: null, id: null, carbonRefSel: "", happinessRefSel: "", industryAvgCarbonRefsSel: [], pbCompanyId: null, pbFieldId: null });

// PE 联动下拉数据源：比赛内公司及其可绑定的数值型产业字段
const pbCompanies = ref<any[]>([]);
const pbFieldsForSelectedCompany = computed(() => {
  const c = pbCompanies.value.find((x: any) => x.id === stockForm.value.pbCompanyId);
  return c?.fields || [];
});
async function loadPbSources() {
  if (!compStore.competitionId) return;
  try {
    const res = await stockApi.pbSources(compStore.competitionId);
    pbCompanies.value = res.companies || [];
  } catch {
    pbCompanies.value = [];
  }
}
function onPbCompanyChange() {
  // 切换关联公司时清空已选字段（字段属于具体公司，不能跨公司复用）
  stockForm.value.pbFieldId = null;
}

// 区域总览卡片（用于绑定股票碳排/幸福度到区域总览字段）
const regionOverview = ref<any[]>([]);
const regionGroups = computed(() => {
  const groups: Record<string, any[]> = {};
  for (const r of regionOverview.value) {
    if (!r.cards || !r.cards.length) continue;
    const cards = r.cards.map((c: any) => ({
      key: `${r.region}::${c.id}`,
      region: r.region,
      cardId: c.id,
      label: `${r.region} / ${c.displayName || c.fieldName || `卡片#${c.id}`}`,
      value: c.value,
      valid: c.valid,
    }));
    (groups[r.region] = groups[r.region] || []).push(...cards);
  }
  return Object.keys(groups).map((region) => ({ region, cards: groups[region] }));
});
// 扁平化所有区域卡片（去掉区域分组分栏），供绑定下拉直接渲染「地区 / 字段名」选项。
const regionCards = computed(() => {
  const out: any[] = [];
  for (const g of regionGroups.value) out.push(...g.cards);
  return out;
});

function findCard(sel: string): any | null {
  if (!sel) return null;
  const [region, cardIdStr] = sel.split("::");
  const cardId = cardIdStr; // 卡片 id 为字符串（如 "c-1690000000000-123"），不可转 number
  for (const r of regionOverview.value) {
    if (r.region === region) {
      const c = r.cards.find((x: any) => x.id === cardId);
      if (c) {
        const base = c.displayName || c.fieldName || `卡片#${c.id}`;
        return { ...c, region, label: `${region} / ${base}` };
      }
    }
  }
  return null;
}
function parseRef(refJson?: string | null): { region: string; cardId: string } | null {
  if (!refJson) return null;
  try {
    const v = JSON.parse(refJson);
    const region = v?.region;
    const cardId = v?.cardId;
    if (typeof region === "string" && (typeof cardId === "string" || typeof cardId === "number")) {
      return { region, cardId: String(cardId) };
    }
  } catch {
    /* 忽略 */
  }
  return null;
}
function resolveRefSel(refJson?: string | null): string {
  const ref = parseRef(refJson);
  return ref ? `${ref.region}::${ref.cardId}` : "";
}
function buildRefJson(sel: string): string | null {
  if (!sel) return null;
  const [region, cardIdStr] = sel.split("::");
  // 卡片 id 为字符串（如 "c-1690000000000-123"），原 Number() 会转成 NaN → 序列化后 cardId:null 触发 400
  if (!cardIdStr) return null;
  return JSON.stringify({ region, cardId: cardIdStr });
}

// 行业碳排均值「多字段绑定」：JSON 数组字符串 ↔ 多选 key 数组（region::cardId）。
function resolveRefsSel(refJson?: string | null): string[] {
  if (!refJson) return [];
  try {
    const arr = JSON.parse(refJson);
    if (!Array.isArray(arr)) return [];
    return arr
      .filter(
        (x: any) =>
          x &&
          typeof x.region === "string" &&
          (typeof x.cardId === "string" || typeof x.cardId === "number"),
      )
      .map((x: any) => `${x.region}::${String(x.cardId)}`);
  } catch {
    return [];
  }
}
function buildRefsJson(sel: string[]): string | null {
  if (!sel || !sel.length) return null;
  const refs = sel
    .map((s) => {
      const [region, cardIdStr] = s.split("::");
      return cardIdStr ? { region, cardId: cardIdStr } : null;
    })
    .filter(Boolean);
  return refs.length ? JSON.stringify(refs) : null;
}

const carbonBound = computed(() => !!stockForm.value.carbonRefSel);
const carbonBoundCard = computed(() => findCard(stockForm.value.carbonRefSel));
const carbonBoundLabel = computed(() => carbonBoundCard.value?.label || "");
const carbonLiveText = computed(() => {
  const c = carbonBoundCard.value;
  if (!c) return "—";
  if (!c.valid) return "字段失效";
  return c.value == null ? "—" : fmt(c.value);
});
const happinessBound = computed(() => !!stockForm.value.happinessRefSel);
const happinessBoundCard = computed(() => findCard(stockForm.value.happinessRefSel));
const happinessBoundLabel = computed(() => happinessBoundCard.value?.label || "");
const happinessLiveText = computed(() => {
  const c = happinessBoundCard.value;
  if (!c) return "—";
  if (!c.valid) return "字段失效";
  return c.value == null ? "—" : fmt(c.value);
});
const industryAvgCarbonBound = computed(() => (stockForm.value.industryAvgCarbonRefsSel || []).length > 0);
const industryAvgCarbonLiveText = computed(() => {
  const sels = stockForm.value.industryAvgCarbonRefsSel || [];
  if (!sels.length) return "—";
  const vals: number[] = [];
  for (const sel of sels) {
    const c = findCard(sel);
    if (c && c.valid && c.value != null) {
      const n = typeof c.value === "number" ? c.value : Number(c.value);
      if (Number.isFinite(n)) vals.push(n);
    }
  }
  if (!vals.length) return "字段失效";
  const avg = vals.reduce((s, v) => s + v, 0) / vals.length;
  return fmt(Math.round(avg * 100) / 100);
});

const accountDialogVisible = ref(false);
const accountForm = ref<any>({ id: null, name: "", ownerType: "USER", companyId: null, userId: null, cashBalance: 1000000, bindFieldId: null, manualCash: false });

const scopedCompanies = computed(() => {
  if (canManage.value) return companies.value;
  const scopes = authStore.user?.stockCompanyScopes || [];
  return companies.value.filter((c) => scopes.includes(c.id));
});

// 公司字段绑定相关
const accountFieldsForCompany = computed(() => {
  if (!accountForm.value.companyId) return [];
  const c = pbCompanies.value.find((x: any) => x.id === accountForm.value.companyId);
  return c?.fields || [];
});
const accountBoundFieldValue = computed(() => {
  if (!accountForm.value.bindFieldId) return null;
  const field = accountFieldsForCompany.value.find((f: any) => f.id === accountForm.value.bindFieldId);
  // 需要从后端获取字段当前值，这里先返回 null，实际值在对话框打开时加载
  return accountForm.value._bindFieldValue ?? null;
});

function onAccountTypeChange() {
  accountForm.value.companyId = null;
  accountForm.value.bindFieldId = null;
  accountForm.value._bindFieldValue = null;
  // 个人账户初始资金固定 100 万，不显示手工现金框；公司账户默认隐藏（现金须由绑定字段驱动）
  accountForm.value.manualCash = false;
}
function onAccountCompanyChange() {
  accountForm.value.bindFieldId = null;
  accountForm.value._bindFieldValue = null;
  // 选定归属公司后隐藏手动初始现金，强制先绑定产业字段（选「不绑定」可恢复）
  accountForm.value.manualCash = false;
}
async function onAccountFieldChange(val?: number | null) {
  const fieldId = val ?? accountForm.value.bindFieldId;
  if (!fieldId || !accountForm.value.companyId) {
    // 选择「不绑定（手动输入）」：恢复手工初始现金
    accountForm.value.bindFieldId = null;
    accountForm.value._bindFieldValue = null;
    accountForm.value.manualCash = true;
    return;
  }
  accountForm.value.bindFieldId = fieldId;
  accountForm.value.manualCash = false;
  // 获取字段当前值
  try {
    const res = await stockApi.pbSources(compStore.competitionId!);
    const company = res.companies?.find((c: any) => c.id === accountForm.value.companyId);
    const field = company?.fields?.find((f: any) => f.id === fieldId);
    if (field) {
      // 需要获取字段的实际值，通过查询公司字段值；无写入值则回退字段初始值 defaultValue
      const res = await companyFieldsApi.get(accountForm.value.companyId);
      const fieldValue = (res?.fields || []).find((fv: any) => fv.id === fieldId);
      const raw = fieldValue?.value != null ? fieldValue.value : fieldValue?.defaultValue;
      accountForm.value._bindFieldValue = raw != null ? Number(raw) : null;
      if (accountForm.value._bindFieldValue != null) {
        accountForm.value.cashBalance = accountForm.value._bindFieldValue;
      }
    }
  } catch {
    accountForm.value._bindFieldValue = null;
  }
}

const fmt = formatMoney;
function companyName(id: number | null): string {
  if (id == null) return "—";
  return companies.value.find((c) => c.id === id)?.name || `公司#${id}`;
}

async function reloadStocks() {
  if (!compStore.competitionId) return;
  loadingStocks.value = true;
  try {
    const res = await stockApi.list(1, 200, compStore.competitionId);
    stocks.value = res.items || res || [];
  } finally {
    loadingStocks.value = false;
  }
}
async function reloadAccounts() {
  if (!compStore.competitionId) return;
  loadingAccounts.value = true;
  try {
    accounts.value = await stockApi.listAccounts(compStore.competitionId);
  } finally {
    loadingAccounts.value = false;
  }
}
async function reloadCompanies() {
  if (!compStore.competitionId) return;
  const res = await companiesApi.list({ competitionId: compStore.competitionId });
  companies.value = res.items || res || [];
}
async function loadRegionOverview() {
  if (!compStore.competitionId) return;
  try {
    regionOverview.value = (await regionsApi.mapOverview(compStore.competitionId)) || [];
  } catch {
    regionOverview.value = [];
  }
}
async function reloadOverview() {
  if (!compStore.competitionId) return;
  loadingOverview.value = true;
  try {
    overview.value = await stockApi.accountOverview(compStore.competitionId);
  } catch {
    overview.value = [];
  } finally {
    loadingOverview.value = false;
  }
}

async function reloadAll() {
  await Promise.all([reloadStocks(), reloadAccounts(), reloadCompanies(), loadRegionOverview(), loadPbSources()]);
  if (canSuper.value) await reloadOverview();
}

function openStockDialog(row?: any) {
  stockForm.value = row
    ? { ...row, carbonRefSel: resolveRefSel(row.carbonFieldRef), happinessRefSel: resolveRefSel(row.happinessFieldRef), industryAvgCarbonRefsSel: resolveRefsSel(row.industryAvgCarbonRefs), pbCompanyId: row.pbCompanyId ?? null, pbFieldId: row.pbFieldId ?? null }
    : { code: "", name: "", totalShares: 0, initNetProfit: 0, currentCarbon: 0, industryAvgCarbon: 0, happiness: 50, companyId: null, id: null, carbonRefSel: "", happinessRefSel: "", industryAvgCarbonRefsSel: [], pbCompanyId: null, pbFieldId: null };
  // 确保 PE 联动下拉数据源就绪（编辑已关联股票时字段选项依赖它）
  if (!pbCompanies.value.length) loadPbSources();
  stockDialogVisible.value = true;
}
async function saveStock() {
  const f = stockForm.value;
  if (!f.code || !f.name) return ElMessage.warning("请填写代码与股票名称");
  const payload = {
    code: f.code,
    name: f.name,
    totalShares: f.totalShares,
    initNetProfit: f.initNetProfit,
    currentCarbon: f.currentCarbon,
    industryAvgCarbon: f.industryAvgCarbon,
    happiness: f.happiness,
    companyId: f.companyId || null,
    carbonFieldRef: buildRefJson(f.carbonRefSel),
    happinessFieldRef: buildRefJson(f.happinessRefSel),
    industryAvgCarbonRefs: buildRefsJson(f.industryAvgCarbonRefsSel),
    pbCompanyId: f.pbCompanyId || null,
    pbFieldId: f.pbFieldId || null,
    competitionId: compStore.competitionId,
  };
  try {
    if (f.id) await stockApi.update(f.id, payload);
    else await stockApi.create(payload);
    ElMessage.success("已保存");
    stockDialogVisible.value = false;
    await reloadStocks();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}
async function removeStock(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除股票「${row.name}」？若有挂单或持仓将拒绝。`, "删除确认", { type: "warning" });
  } catch {
    return;
  }
  try {
    await stockApi.remove(row.id, compStore.competitionId);
    ElMessage.success("已删除");
    await reloadStocks();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

function openAccountDialog(row?: any) {
  const base = row
    ? { ...row, cashBalance: row.cashBalance, bindFieldId: row.bindFieldId || null, _bindFieldValue: null }
    : { id: null, name: "", ownerType: "USER", companyId: null, userId: null, cashBalance: 1000000, bindFieldId: null, _bindFieldValue: null };
  // 个人账户初始资金固定 100 万，不显示手工现金框；公司账户仅「不绑定字段」时手动
  base.manualCash = base.ownerType === "COMPANY" && !base.bindFieldId;
  accountForm.value = base;
  // 加载公司字段数据
  if (!pbCompanies.value.length) loadPbSources();
  accountDialogVisible.value = true;
}
async function saveAccount() {
  const f = accountForm.value;
  if (!f.name) return ElMessage.warning("请填写账户名");
  try {
    if (f.id) {
      const payload: any = { name: f.name, bindFieldId: f.bindFieldId || null };
      // 绑定产业字段后，现金余额由字段值驱动，无需（也不应）回写 cashBalance；
      // 个人账户初始资金固定 100 万，也不回写 cashBalance
      if (!f.bindFieldId && f.ownerType === "COMPANY") payload.cashBalance = f.cashBalance;
      await stockApi.updateAccount(f.id, payload);
    } else {
      const payload: any = { name: f.name, ownerType: f.ownerType, competitionId: compStore.competitionId };
      if (f.ownerType === "COMPANY") {
        if (!f.companyId) return ElMessage.warning("请选择归属公司");
        payload.companyId = f.companyId;
        payload.bindFieldId = f.bindFieldId || null;
        if (!f.bindFieldId) payload.cashBalance = f.cashBalance;
      } else {
        // 个人账户初始资金固定 100 万，由后端强制，前端不传 cashBalance
        payload.userId = authStore.user?.id;
      }
      await stockApi.createAccount(payload);
    }
    ElMessage.success("已保存");
    accountDialogVisible.value = false;
    await reloadAccounts();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}
async function removeAccount(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除账户「${row.name}」？若有持仓/挂单将拒绝。`, "删除确认", { type: "warning" });
  } catch {
    return;
  }
  try {
    await stockApi.removeAccount(row.id);
    ElMessage.success("已删除");
    await reloadAccounts();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

// 做市商配置
const mmDialogVisible = ref(false);
const mmConfig = ref({
  enabled: true,
  spreadPct: 2,
  levels: 3,
  baseQuantity: 1000,
});

// S8：股票引擎参数（比赛级 stockConfig 的默认值，推进时可临时覆盖）
const stockConfigForm = ref({
  limitPct: 0.1,
  maxMovePct: 0.05,
  happinessImpact: 0.2,
  carbonImpact: 0.2,
  carbonSaturateRatio: 2,
  mmDepthPct: 0.001,
  mmSpreadPct: 0.02,
  interventionMode: "regression" as "regression" | "expand-limit",
  regressionPct: 0.02,
  tradePriceWeight: 0.7,
});

// S9：本轮定价诊断
const advanceResults = ref<any[]>([]);
const diagVisible = ref(false);
function fmtNum(v: number | undefined, digits = 3): string {
  return v == null || Number.isNaN(v) ? "-" : String(Number(v).toFixed(digits));
}

function openAdvanceDialog() {
  mmDialogVisible.value = true;
}

async function confirmAdvance() {
  mmDialogVisible.value = false;
  try {
    const res = await stockApi.advanceRound(compStore.competitionId!, {
      marketMaker: mmConfig.value,
      stockConfig: stockConfigForm.value,
    });
    const mmInfo = res.marketMakerOrders > 0 ? `，做市商挂单 ${res.marketMakerOrders} 笔` : "";
    ElMessage.success(`已推进，处理 ${res.advanced} 只股票${mmInfo}`);
    advanceResults.value = Array.isArray(res.results) ? res.results : [];
    if (advanceResults.value.length) diagVisible.value = true;
    await reloadStocks();
    await reloadAccounts(); // 字段联动账户余额随交易更新，需刷新现金显示
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

// 绑定产业字段的资金账户（现金实时=字段值）与 PE 联动的股票（有效PE=字段值），
// 当公司产业字段被合同 / 财年定时器 / 计算图改写时，刷新账户与股票列表以同步显示。
// 账户总览（总资产 / 持仓市值 / 历史盈亏 / 可用资金）同样依赖这些数据，须一并实时刷新。
let accountReloadTimer: ReturnType<typeof setTimeout> | undefined;
function scheduleAccountReload() {
  if (accountReloadTimer) clearTimeout(accountReloadTimer);
  accountReloadTimer = setTimeout(() => {
    accountReloadTimer = undefined;
    if (compStore.competitionId) {
      reloadAccounts();
      reloadStocks();
      if (canSuper.value) reloadOverview();
    }
  }, 400);
}
useResourceChanged("company-field", scheduleAccountReload);
// 股价 / 持仓 / 总资产随推进轮次与撮合变动，账户总览须实时刷新
useResourceChanged("stocks", scheduleAccountReload);
// 下单 / 撤单瞬间（stock-orders 资源）立即刷新总览，确保冻结 / 回滚现金即时可见
useResourceChanged("stock-orders", scheduleAccountReload);
// 资金账户本身的创建 / 编辑 / 删除（stock-accounts 资源）须同步刷新总览
useResourceChanged("stock-accounts", scheduleAccountReload);
// 持仓随撮合逐条变动（stock-holdings 资源）须同步刷新总览的持仓市值 / 总资产
useResourceChanged("stock-holdings", scheduleAccountReload);

onMounted(reloadAll);
onBeforeUnmount(() => {
  if (accountReloadTimer) {
    clearTimeout(accountReloadTimer);
    accountReloadTimer = undefined;
  }
});
</script>

<style scoped>
.stock-manage {
  width: 100%;
}
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
.block-card {
  margin-bottom: 16px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border, #ebeef5);
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-title {
  font-weight: 600;
  font-size: 14px;
}
.card-actions {
  display: flex;
  gap: 8px;
}
.muted {
  color: var(--color-text-tertiary, #92969e);
}
.form-hint {
  font-size: 12px;
  color: var(--color-text-tertiary, #92969e);
  margin-top: 4px;
  line-height: 1.4;
}
.pb-hint {
  margin-bottom: 12px;
  font-size: 12px;
}
.field-hint {
  font-size: 12px;
  color: var(--color-text-secondary, #5a5f6a);
  margin-top: 4px;
}
.field-hint b {
  color: var(--color-primary, #409eff);
}
.bound-value {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
}
.bound-num {
  font-weight: 600;
}
.bind-tag {
  margin-left: 4px;
  font-size: 11px;
  line-height: 16px;
  height: 18px;
  padding: 0 5px;
}
.field-link-tag {
  margin-left: 6px;
  vertical-align: middle;
}
/* 账户总览：红涨绿跌（中国股票惯例） */
.up {
  color: #f5483b;
  font-weight: 600;
}
.down {
  color: #16a34a;
  font-weight: 600;
}
.holding-detail {
  padding: 8px 12px;
}
.holding-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.holding-table th,
.holding-table td {
  border-bottom: 1px solid var(--color-border, #ebeef5);
  padding: 4px 8px;
  text-align: left;
  white-space: nowrap;
}
.holding-table th {
  color: var(--color-text-tertiary, #92969e);
  font-weight: 500;
}
.holding-table .num {
  text-align: right;
}
</style>
