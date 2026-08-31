<template>
  <div class="stock-market">
    <div class="mm-toolbar">
      <h2 class="mm-title">股票行情</h2>
      <div class="mm-actions">
        <el-tag type="info" effect="plain">轮次：{{ maxRound }}</el-tag>
        <el-button :icon="Refresh" @click="reloadAll">刷新</el-button>
      </div>
    </div>

    <div class="market-body">
      <!-- 左：股票列表 + K线 -->
      <div class="market-main">
        <el-card shadow="never" class="block-card">
          <template #header>
            <span class="card-title">股票列表</span>
          </template>
          <div v-loading="loadingStocks" class="stock-grid">
            <div
              v-for="s in stocks"
              :key="s.id"
              class="stock-card"
              :class="{ active: s.id === selectedStockId }"
              @click="selectStock(s.id)"
            >
              <div class="stock-main">
                <div class="stock-name">{{ s.name }}</div>
                <div class="stock-code">{{ s.code }}</div>
              </div>
              <div class="stock-center">
                <div class="stock-price">¥{{ fmt(s.currentPrice) }}</div>
                <div class="stock-change" :class="changeClass(s.changePct)">
                  <span class="chg-pct">{{ s.changePct > 0 ? "+" : "" }}{{ fmt(s.changePct) }}%</span>
                  <span class="chg-price">{{ s.changePrice > 0 ? "+" : "" }}{{ fmt(s.changePrice) }}</span>
                </div>
              </div>
            </div>
            <div v-if="!loadingStocks && stocks.length === 0" class="empty-hint">暂无股票</div>
          </div>
        </el-card>

        <el-card shadow="never" class="block-card chart-card" :body-style="{ padding: '0' }">
          <template #header>
            <div v-if="selectedStock" class="chart-header">
              <span class="card-title">{{ selectedStock.name }}</span>
              <span class="chart-code">{{ selectedStock.code }}</span>
              <span class="chart-price" :class="changeClass(selectedStock.changePct)">¥{{ fmt(selectedStock.currentPrice) }}</span>
              <span class="chart-change" :class="changeClass(selectedStock.changePct)">
                {{ selectedStock.changePct > 0 ? "+" : "" }}{{ fmt(selectedStock.changePct) }}%
              </span>
              <span class="chart-ma-legend">
                <span class="ma-tag ma5">MA5</span>
                <span class="ma-tag ma10">MA10</span>
                <span class="ma-tag ma20">MA20</span>
              </span>
            </div>
          </template>
          <div v-if="selectedStock" ref="chartRef" class="kline-chart" v-loading="loadingCandles"></div>
          <div v-if="selectedStock" class="chart-hint">滚轮缩放 · 拖拽平移 · 底部滑块 · MA5/MA10/MA20</div>
          <div v-else class="chart-empty">
            <el-icon :size="40" class="chart-empty-icon"><TrendCharts /></el-icon>
            <p class="chart-empty-text">{{ emptyChartText }}</p>
          </div>
        </el-card>
      </div>

      <!-- 右：选购 / 买卖面板 -->
      <div class="market-side">
        <el-card shadow="never" class="block-card">
          <template #header><span class="card-title">交易面板</span></template>
          <el-form label-position="top" size="small">
            <el-form-item label="资金账户">
              <el-select
                v-model="selectedAccountId"
                placeholder="选择资金账户"
                style="width: 100%"
                @change="onAccountChange"
              >
                <el-option
                  v-for="a in accounts"
                  :key="a.id"
                  :label="`${a.name}（${a.ownerType === 'USER' ? '个人' : '公司'}）`"
                  :value="a.id"
                />
              </el-select>
            </el-form-item>
            <div v-if="currentAccount" class="cash-line">
              现金余额：<b>{{ fmt(currentAccount.fieldBalance != null ? currentAccount.fieldBalance : currentAccount.cashBalance) }}</b> 元
            </div>

            <el-form-item label="方向">
              <el-radio-group v-model="trade.side">
                <el-radio-button value="BUY">买入</el-radio-button>
                <el-radio-button value="SELL">卖出</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item label="委托价（元/股）">
              <el-input-number
                v-model="trade.price"
                :min="priceLimit.lower"
                :max="priceLimit.upper"
                :step="0.01"
                :precision="2"
                style="width: 100%"
              />
              <div class="price-hint" v-if="selectedStock">
                限价范围：¥{{ fmt(priceLimit.lower) }} ~ ¥{{ fmt(priceLimit.upper) }}（±10%）
              </div>
            </el-form-item>

            <el-form-item label="数量（股）">
              <el-input-number
                v-model="trade.quantity"
                :min="1"
                :step="100"
                :precision="0"
                style="width: 100%"
              />
            </el-form-item>

            <div class="est-line">
              预计金额：<b>{{ fmt(estAmount) }}</b> 元
              <span v-if="trade.side === 'SELL' && myHoldingShares > 0" class="muted">
                （可卖 {{ fmt(myHoldingShares) }} 股）
              </span>
            </div>

            <el-button
              type="primary"
              style="width: 100%"
              :disabled="!canTrade"
              @click="submitOrder"
            >
              {{ trade.side === "BUY" ? "买入" : "卖出" }}
            </el-button>
          </el-form>

          <el-divider>我的持仓</el-divider>
          <div v-if="holdings.length" class="holding-list">
            <div v-for="(row, i) in holdings" :key="row.stock?.id ?? i" class="holding-row">
              <span class="holding-cell holding-name">{{ row.stock?.name || row.stock?.code || '—' }}</span>
              <span class="holding-cell holding-shares">{{ fmt(row.shares) }}股</span>
              <span class="holding-cell holding-value">¥{{ fmt(row.marketValue) }}</span>
            </div>
          </div>
          <div v-else class="empty-hint small">暂无持仓</div>

          <el-divider>我的订单</el-divider>
          <div v-if="orders.length" class="order-list">
            <div v-for="row in orders" :key="row.id" class="order-row">
              <span class="order-name">{{ row.stock?.name || row.stock?.code || '—' }}</span>
              <span class="order-side" :class="row.side === 'BUY' ? 'up' : 'down'">{{ row.side === 'BUY' ? '买' : '卖' }}</span>
              <span class="order-price">{{ fmt(row.price) }}</span>
              <span class="order-qty">{{ fmt(row.quantity) }}</span>
              <span class="order-status">
                <el-tag size="small" :type="row.status === 'PENDING' ? 'warning' : row.status === 'FILLED' ? 'success' : 'info'" style="font-size:11px; height:20px; padding:0 4px;">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </span>
              <span class="order-action">
                <el-button v-if="row.status === 'PENDING'" link type="danger" @click="cancelOrder(row.id)" style="font-size:12px;">撤</el-button>
              </span>
            </div>
          </div>
          <div v-else class="empty-hint small">暂无订单</div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from "vue";
import * as echarts from "echarts";
import { Refresh, TrendCharts } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { stockApi } from "@/api";
import { useCompetitionStore } from "@/stores/competition";
import { useAuthStore } from "@/stores/auth";
import { useResourceChanged } from "@/realtime/useResourceChanged";
import { formatMoney } from "@/utils/format";

const compStore = useCompetitionStore();
const authStore = useAuthStore();

interface Stock {
  id: number;
  code: string;
  name: string;
  currentPrice: number;
  initPrice: number;
  round: number;
  industryPE: number;
  happiness: number;
  changePct: number;
  changePrice: number;
}
interface Candle {
  round: number;
  open: number;
  high: number;
  low: number;
  close: number;
  changePct: number;
}
interface Account {
  id: number;
  name: string;
  ownerType: string;
  cashBalance: number;
  bindFieldId?: number | null;
  fieldBalance?: number | null;
}
interface Holding {
  stock: { id: number; code: string; name: string };
  shares: number;
  costPrice: number;
  marketValue: number;
}
interface Order {
  id: number;
  stock?: { code: string; name?: string };
  side: string;
  price: number;
  quantity: number;
  status: string;
}

const stocks = ref<Stock[]>([]);
const selectedStockId = ref<number | null>(null);
const selectedStock = computed(() => stocks.value.find((s) => s.id === selectedStockId.value) || null);
const emptyChartText = computed(() =>
  stocks.value.length ? "请选择左侧股票查看 K 线" : "当前比赛暂无股票，请先在「股票管理」中创建",
);
const candles = ref<Candle[]>([]);
const accounts = ref<Account[]>([]);
const selectedAccountId = ref<number | null>(null);
const currentAccount = computed(() => accounts.value.find((a) => a.id === selectedAccountId.value) || null);
const holdings = ref<Holding[]>([]);
const orders = ref<Order[]>([]);

const loadingStocks = ref(false);
const loadingCandles = ref(false);

const trade = ref({ side: "BUY", price: 0, quantity: 100 });
const maxRound = computed(() => stocks.value.reduce((m, s) => Math.max(m, s.round), 0));

const myHoldingShares = computed(() => {
  if (!selectedStockId.value) return 0;
  const h = holdings.value.find((x) => x.stock && x.stock.id === selectedStockId.value);
  return h ? h.shares : 0;
});
// 委托价限价范围（当前价 ±10%）
const priceLimit = computed(() => {
  const price = selectedStock.value?.currentPrice || 0;
  const limit = price * 0.1;
  const lower = Math.max(0.01, Math.round((price - limit) * 100) / 100);
  // 未选股票时 price=0 → lower=0.01 > upper=0，会触发 el-input-number 的 min>max 异常；用 max 兜底保证 upper>=lower
  const upper = Math.max(lower, Math.round((price + limit) * 100) / 100);
  return { lower, upper };
});
const estAmount = computed(() => Math.round(trade.value.price * trade.value.quantity * 100) / 100);
const canTrade = computed(() => !!selectedAccountId.value && !!selectedStockId.value && trade.value.price > 0 && trade.value.quantity > 0);

const chartRef = ref<HTMLElement | null>(null);
let chart: echarts.ECharts | null = null;

const fmt = formatMoney;
function changeClass(v: number): string {
  if (v > 0) return "up";
  if (v < 0) return "down";
  return "";
}
function statusLabel(s: string): string {
  return s === "PENDING" ? "挂单" : s === "FILLED" ? "已成" : "已撤";
}

async function reloadStocks() {
  if (!compStore.competitionId) return;
  loadingStocks.value = true;
  try {
    const res = await stockApi.list(1, 200, compStore.competitionId);
    stocks.value = (res.items || res || []).map((s: any) => ({ ...s, changePct: 0, changePrice: 0 }) as Stock);
    // 计算每只股票最近一轮涨跌幅与涨跌额（取最后一根 K 线的 close-open）
    await Promise.all(
      stocks.value.map(async (s) => {
        try {
          const c = await stockApi.candles(s.id);
          const last = c.candles.length ? c.candles[c.candles.length - 1] : null;
          if (last) {
            s.changePct = last.changePct;
            s.changePrice = Math.round((last.close - last.open) * 100) / 100;
          }
        } catch {
          s.changePct = 0;
          s.changePrice = 0;
        }
      }),
    );
    const current = stocks.value.find((s) => s.id === selectedStockId.value);
    if (!current && stocks.value.length) selectStock(stocks.value[0].id);
  } finally {
    loadingStocks.value = false;
  }
}

async function reloadAccounts() {
  if (!compStore.competitionId) return;
  accounts.value = await stockApi.listAccounts(compStore.competitionId);
  if (!selectedAccountId.value && accounts.value.length) {
    selectedAccountId.value = accounts.value[0].id;
    await reloadAccountData();
  }
}

async function reloadAccountData() {
  if (!selectedAccountId.value) {
    holdings.value = [];
    orders.value = [];
    return;
  }
  holdings.value = await stockApi.accountHoldings(selectedAccountId.value);
  // 按当前选中的资金账户过滤订单，只显示该账户的挂单/历史
  orders.value = await stockApi.listOrders(compStore.competitionId!, selectedStockId.value || undefined, selectedAccountId.value);
}

async function loadCandles(id: number) {
  loadingCandles.value = true;
  try {
    const res = await stockApi.candles(id);
    candles.value = res.candles || [];
    await nextTick();
    renderChart();
  } finally {
    loadingCandles.value = false;
  }
}

function selectStock(id: number) {
  selectedStockId.value = id;
  const s = stocks.value.find((x) => x.id === id);
  if (s) trade.value.price = s.currentPrice;
  loadCandles(id);
  reloadAccountData();
}
async function onAccountChange() {
  await reloadAccountData();
}

// 计算移动平均线数据
function calcMA(data: number[][], period: number): (number | null)[] {
  return data.map((_, i) => {
    if (i < period - 1) return null;
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += data[j][1]; // close price
    return +(sum / period).toFixed(2);
  });
}

function renderChart() {
  if (!chartRef.value) return;
  if (!chart) chart = echarts.init(chartRef.value);

  // ECharts 蜡烛图数据格式：[开盘, 收盘, 最低, 最高]
  const ohlc = candles.value.map((c) => [c.open, c.close, c.low, c.high]);
  const volumes = candles.value.map((c) => ({
    value: c.close,
    volume: Math.abs(c.close - c.open) > 0 ? Math.round(c.close * 100) : 0, // 模拟成交量
    isUp: c.close >= c.open,
  }));
  const roundLabels = candles.value.map((c) => `R${c.round}`);

  // 移动平均线
  const ma5 = calcMA(ohlc, 5);
  const ma10 = calcMA(ohlc, 10);
  const ma20 = calcMA(ohlc, 20);

  // 默认显示范围
  const maxVisible = 30;
  const total = candles.value.length;
  const defaultStart = total > maxVisible ? Math.round((1 - maxVisible / total) * 100) : 0;

  // 暗色主题配色
  const bg = "#1a1a2e";
  const gridColor = "#2a2a3e";
  const textColor = "#8a8a9a";
  const upColor = "#ec0000";
  const downColor = "#00a800";

  chart.setOption({
    backgroundColor: bg,
    animation: false,
    grid: [
      { left: 60, right: 60, top: 30, bottom: 100 },  // 主图（K线 + MA）
      { left: 60, right: 60, top: "82%", bottom: 28 },  // 成交量
    ],
    axisPointer: {
      link: [{ xAxisIndex: [0, 1] }],  // 主图和成交量联动
      label: { backgroundColor: "#3a3a4e", color: "#fff", fontSize: 11 },
    },
    xAxis: [
      {
        type: "category",
        data: roundLabels,
        gridIndex: 0,
        axisLine: { lineStyle: { color: gridColor } },
        axisTick: { lineStyle: { color: gridColor } },
        axisLabel: { color: textColor, fontSize: 11 },
        splitLine: { show: false },
        axisPointer: { z: 100 },
      },
      {
        type: "category",
        data: roundLabels,
        gridIndex: 1,
        axisLine: { lineStyle: { color: gridColor } },
        axisTick: { lineStyle: { color: gridColor } },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        position: "right",
        axisLine: { lineStyle: { color: gridColor } },
        axisTick: { lineStyle: { color: gridColor } },
        axisLabel: { color: textColor, fontSize: 11, formatter: (v: number) => v.toFixed(2) },
        splitLine: { lineStyle: { color: gridColor, type: "dashed" } },
      },
      {
        scale: true,
        gridIndex: 1,
        position: "right",
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: [0, 1],
        start: defaultStart,
        end: 100,
        minValueSpan: 5,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
      },
      {
        type: "slider",
        xAxisIndex: [0, 1],
        start: defaultStart,
        end: 100,
        height: 18,
        bottom: 6,
        borderColor: "transparent",
        backgroundColor: "#16162a",
        fillerColor: "rgba(100, 100, 180, 0.2)",
        handleStyle: { color: "#4a4a6a", borderColor: "#4a4a6a" },
        textStyle: { color: textColor, fontSize: 10 },
        dataBackground: {
          lineStyle: { color: "#3a3a4e", opacity: 0.5 },
          areaStyle: { color: "#2a2a3e", opacity: 0.3 },
        },
        selectedDataBackground: {
          lineStyle: { color: "#4a4a6a" },
          areaStyle: { color: "#2a2a3e" },
        },
      },
    ],
    tooltip: {
      trigger: "axis",
      axisPointer: {
        type: "cross",
        lineStyle: { color: "#555", type: "dashed" },
        crossStyle: { color: "#555" },
      },
      backgroundColor: "rgba(30, 30, 50, 0.95)",
      borderColor: "#3a3a4e",
      textStyle: { color: "#e0e0e0", fontSize: 12 },
      formatter: (params: any) => {
        if (!params || !params.length) return "";
        const round = params[0].axisValue;
        let html = `<div style="font-weight:600;margin-bottom:6px;color:#fff">${round}</div>`;
        for (const p of params) {
          if (p.seriesType !== "candlestick") continue;
          const v = p.value || [];
          const [o, c, l, h] = v.length >= 5 ? [v[1], v[2], v[3], v[4]] : [v[0], v[1], v[2], v[3]];
          const isUp = c >= o;
          const color = isUp ? upColor : downColor;
          const chg = o !== 0 ? (((c - o) / o) * 100).toFixed(2) : "0.00";
          html += `<div style="display:flex;justify-content:space-between;gap:16px;"><span style="color:${textColor}">开盘</span><span style="color:${color}">¥${fmt(o)}</span></div>`;
          html += `<div style="display:flex;justify-content:space-between;gap:16px;"><span style="color:${textColor}">收盘</span><span style="color:${color}">¥${fmt(c)}</span></div>`;
          html += `<div style="display:flex;justify-content:space-between;gap:16px;"><span style="color:${textColor}">最低</span><span style="color:${downColor}">¥${fmt(l)}</span></div>`;
          html += `<div style="display:flex;justify-content:space-between;gap:16px;"><span style="color:${textColor}">最高</span><span style="color:${upColor}">¥${fmt(h)}</span></div>`;
          html += `<div style="display:flex;justify-content:space-between;gap:16px;margin-top:4px;padding-top:4px;border-top:1px solid #3a3a4e;"><span style="color:${textColor}">涨跌</span><span style="color:${color}">${isUp ? "+" : ""}${chg}%</span></div>`;
        }
        // MA 值
        const idx = roundLabels.indexOf(round);
        if (idx >= 0) {
          html += `<div style="margin-top:6px;padding-top:6px;border-top:1px solid #3a3a4e;">`;
          if (ma5[idx] != null) html += `<div style="color:#f5a623;font-size:11px;">MA5: ¥${fmt(ma5[idx])}</div>`;
          if (ma10[idx] != null) html += `<div style="color:#4b83c1;font-size:11px;">MA10: ¥${fmt(ma10[idx])}</div>`;
          if (ma20[idx] != null) html += `<div style="color:#e5484d;font-size:11px;">MA20: ¥${fmt(ma20[idx])}</div>`;
          html += `</div>`;
        }
        return html;
      },
    },
    series: [
      // K 线（蜡烛图）
      {
        name: "K线",
        type: "candlestick",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ohlc,
        itemStyle: {
          color: upColor,         // 涨：红填充
          color0: downColor,      // 跌：绿填充
          borderColor: upColor,
          borderColor0: downColor,
          borderWidth: 1,
        },
        barMaxWidth: 20,
        barMinWidth: 8,
      },
      // MA5
      {
        name: "MA5",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma5,
        showSymbol: false,
        lineStyle: { color: "#f5a623", width: 1 },
        smooth: true,
      },
      // MA10
      {
        name: "MA10",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma10,
        showSymbol: false,
        lineStyle: { color: "#4b83c1", width: 1 },
        smooth: true,
      },
      // MA20
      {
        name: "MA20",
        type: "line",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ma20,
        showSymbol: false,
        lineStyle: { color: "#e5484d", width: 1 },
        smooth: true,
      },
      // 成交量（柱状图，涨红跌绿）
      {
        name: "成交量",
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes.map((v) => ({
          value: v.volume,
          itemStyle: { color: v.isUp ? upColor : downColor, opacity: 0.7 },
        })),
        barMaxWidth: 16,
        barMinWidth: 4,
      },
    ],
  });
  chart.resize();
}

async function submitOrder() {
  if (!canTrade.value || !selectedStockId.value || !selectedAccountId.value) return;
  try {
    await stockApi.placeOrder({
      stockId: selectedStockId.value,
      fundsAccountId: selectedAccountId.value,
      side: trade.value.side,
      price: trade.value.price,
      quantity: trade.value.quantity,
    });
    ElMessage.success("委托已提交，将在下一轮撮合");
    await reloadAccountData();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}
async function cancelOrder(id: number) {
  try {
    await stockApi.cancelOrder(id);
    await reloadAccountData();
  } catch {
    // 错误提示由全局响应拦截器统一弹出，避免重复 toast
  }
}

async function reloadAll() {
  await Promise.all([reloadStocks(), reloadAccounts()]);
}

function onResize() {
  chart?.resize();
}

watch(selectedStock, (val) => {
  if (!val && chart) {
    chart.dispose();
    chart = null;
  }
});

// 绑定产业字段的资金账户，现金余额实时等于字段值。
// 公司产业字段被合同 / 财年定时器 / 计算图改写时，刷新账户列表以同步交易面板的现金余额。
let accountReloadTimer: ReturnType<typeof setTimeout> | undefined;
function scheduleAccountReload() {
  if (accountReloadTimer) clearTimeout(accountReloadTimer);
  accountReloadTimer = setTimeout(() => {
    accountReloadTimer = undefined;
    reloadAccounts();
  }, 400);
}
useResourceChanged("company-field", scheduleAccountReload);

onMounted(async () => {
  window.addEventListener("resize", onResize);
  await reloadAll();
});
onBeforeUnmount(() => {
  window.removeEventListener("resize", onResize);
  if (accountReloadTimer) clearTimeout(accountReloadTimer);
  if (chart) {
    chart.dispose();
    chart = null;
  }
});
</script>

<style scoped>
.stock-market {
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
  align-items: center;
  gap: 8px;
}
.market-body {
  display: grid;
  grid-template-columns: 1fr 400px;
  gap: 16px;
  align-items: start;
}
.market-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.stock-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.stock-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--color-border, #ebeef5);
  border-radius: var(--radius-sm, 10px);
  background: var(--color-surface, #fff);
  cursor: pointer;
  transition: border-color var(--dur-base) var(--ease-standard),
    box-shadow var(--dur-base) var(--ease-standard);
}
.stock-card:hover {
  border-color: var(--color-primary, #409eff);
}
.stock-card.active {
  border-color: var(--color-primary, #409eff);
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.15);
}
.stock-main {
  min-width: 0;
}
.stock-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stock-code {
  font-size: 12px;
  color: var(--color-text-tertiary, #92969e);
  margin-top: 2px;
}
.stock-price {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text-primary, #303133);
}
.stock-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.stock-change {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.chg-pct {
  font-size: 15px;
  font-weight: 600;
}
.chg-price {
  font-size: 12px;
}
.block-card {
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border, #ebeef5);
}
.card-title {
  font-weight: 600;
  font-size: 14px;
}
.chart-card {
  position: relative;
  overflow: hidden;
  border-radius: 8px;
}
.chart-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.chart-code {
  color: var(--color-text-tertiary, #92969e);
  font-size: 12px;
}
.chart-price {
  font-weight: 700;
  font-size: 16px;
  margin-left: 8px;
}
.chart-change {
  font-weight: 600;
  font-size: 13px;
}
.chart-ma-legend {
  margin-left: auto;
  display: flex;
  gap: 10px;
}
.ma-tag {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 3px;
}
.ma-tag.ma5 { color: #f5a623; background: rgba(245, 166, 35, 0.1); }
.ma-tag.ma10 { color: #4b83c1; background: rgba(75, 131, 193, 0.1); }
.ma-tag.ma20 { color: #e5484d; background: rgba(229, 72, 77, 0.1); }
.kline-chart {
  height: 480px;
  width: 100%;
  cursor: crosshair;
  border-radius: 0 0 8px 8px;
}
.chart-empty {
  height: 480px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: #1a1a2e;
  border-radius: 0 0 8px 8px;
  color: #8a8a9a;
}
.chart-empty-icon {
  opacity: 0.45;
}
.chart-empty-text {
  margin: 0;
  font-size: 14px;
}
.chart-hint {
  text-align: center;
  font-size: 11px;
  color: #6a6a7a;
  padding: 6px 0;
  background: #1a1a2e;
  border-radius: 0 0 8px 8px;
  user-select: none;
}
.market-side {
  position: sticky;
  top: 0;
}
.cash-line,
.est-line {
  font-size: 13px;
  margin-bottom: 10px;
  color: var(--color-text-secondary, #5a5f6a);
}
.est-line b {
  color: var(--color-primary, #409eff);
}
.muted {
  color: var(--color-text-tertiary, #92969e);
  font-size: 12px;
}
.price-hint {
  font-size: 11px;
  color: var(--color-text-tertiary, #92969e);
  margin-top: 4px;
}
.up {
  color: #ec0000;
  font-weight: 600;
}
.down {
  color: #00a800;
  font-weight: 600;
}
.empty-hint {
  color: var(--color-text-tertiary, #92969e);
  text-align: center;
  padding: 24px 0;
}
.empty-hint.small {
  padding: 12px 0;
  font-size: 13px;
}
.market-side :deep(.el-divider) {
  margin: 16px 0 12px;
}
.market-side :deep(.el-table) {
  font-size: 14px;
}
.market-side :deep(.el-table th) {
  font-size: 13px;
}
.market-side :deep(.el-table td) {
  padding: 6px 0;
}
.order-list {
  max-height: 320px;
  overflow-y: auto;
}
.order-row {
  display: flex;
  align-items: center;
  padding: 3px 0;
  border-bottom: 1px solid var(--color-border-light, #ebeef5);
  font-size: 13px;
}
.order-row:last-child {
  border-bottom: none;
}
.order-name {
  width: 20%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: 4px;
}
.order-side {
  width: 15%;
  text-align: center;
  font-weight: 600;
}
.order-price {
  width: 20%;
  text-align: right;
  padding-right: 4px;
}
.order-qty {
  width: 18%;
  text-align: right;
  padding-right: 4px;
}
.order-status {
  width: 15%;
  text-align: center;
  font-size: 12px;
  color: var(--color-text-secondary);
}
.order-action {
  width: 12%;
  text-align: center;
}
.holding-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.holding-row {
  display: flex;
  align-items: center;
  padding: 4px 0;
  font-size: 13px;
}
.holding-cell {
  flex: 1;
  padding: 0 2px;
}
.holding-name {
  flex: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.holding-shares {
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.holding-value {
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
</style>
