/**
 * T-02 验证：股票下单按钮必须防连点 —— 双击只能产生**一笔**委托。
 *
 * 改前 `submitOrder()` 没有任何闸门（按钮也没有 `:loading`）：两次点击各自发一次
 * `POST /stocks/orders`，后端只校验余额、不去重 → 两笔 PENDING 委托（重复占用资金）。
 *
 * 本文件为了「改前/改后」都能跑真实代码：从 SFC 源码抽出 `async function submitOrder() {...}`
 * 的函数体，注入桩（canTrade / selectedStockId / selectedAccountId / trade / stockApi /
 * ElMessage / reloadAccountData / submitting）后执行，统计真实发出的下单请求次数。
 *
 * 用法：
 *   node tests/fix_verify/frontend/test_t02_double_submit.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const viewPath = path.resolve(here, "../../../frontend/src/views/stocks/StockMarketView.vue");
const viewSource = fs.readFileSync(viewPath, "utf8");

const match = viewSource.match(/async function submitOrder\(\) \{([\s\S]*?)\n\}/);
if (!match) {
  console.error("无法从 StockMarketView.vue 抽取 submitOrder 函数体（源码结构变了？）");
  process.exit(2);
}

/**
 * 用视图当前的 submitOrder 真实实现跑一次「双击」场景。
 * @param {object} opts hold: 下单请求返回前是否挂起；reject: 请求是否失败
 */
function makeHarness(opts = {}) {
  const state = {
    placeOrderCalls: [],
    reloadCalls: 0,
    successToasts: 0,
    release: null,
  };
  const pending = [];
  const stockApi = {
    placeOrder(payload) {
      state.placeOrderCalls.push(payload);
      if (!opts.hold) {
        return opts.reject
          ? Promise.reject(new Error("boom"))
          : Promise.resolve({ id: state.placeOrderCalls.length });
      }
      return new Promise((resolve, reject) => {
        pending.push(() => (opts.reject ? reject(new Error("boom")) : resolve({ id: 1 })));
      });
    },
  };
  state.release = () => pending.splice(0).forEach((fn) => fn());

  const scope = {
    canTrade: { value: opts.canTrade !== false },
    selectedStockId: { value: opts.noStock ? null : 7 },
    selectedAccountId: { value: opts.noAccount ? null : 3 },
    trade: { value: { side: "BUY", price: "97", quantity: "100" } },
    stockApi,
    ElMessage: {
      success: () => {
        state.successToasts += 1;
      },
    },
    reloadAccountData: async () => {
      state.reloadCalls += 1;
    },
    submitting: { value: false },
  };

  const fn = new Function(
    ...Object.keys(scope),
    `return (async () => {${match[1]}\n});`,
  )(...Object.values(scope));

  return { state, submitOrder: fn, scope };
}

let pass = 0;
let fail = 0;
const cases = [];

async function check(name, fn) {
  try {
    await fn();
    cases.push(`  [PASS] ${name}`);
    pass += 1;
  } catch (e) {
    cases.push(`  [FAIL] ${name}: ${e.message.split("\n")[0]}`);
    fail += 1;
  }
}

// ---------- 缺陷场景 ----------
await check("请求返回前连点两次：只发一笔委托（改前发两笔）", async () => {
  const { state, submitOrder } = makeHarness({ hold: true });
  const first = submitOrder();
  const second = submitOrder(); // 用户第二次点击
  state.release();
  await Promise.all([first, second]);

  assert.equal(
    state.placeOrderCalls.length,
    1,
    `双击必须只下一笔委托，实际发出 ${state.placeOrderCalls.length} 笔（改前为 2 笔 PENDING 委托）`,
  );
});

await check("连点五次：仍然只发一笔", async () => {
  const { state, submitOrder } = makeHarness({ hold: true });
  const all = [submitOrder(), submitOrder(), submitOrder(), submitOrder(), submitOrder()];
  state.release();
  await Promise.all(all);
  assert.equal(state.placeOrderCalls.length, 1, `实际 ${state.placeOrderCalls.length} 笔`);
});

await check("上一笔完成后可以再次下单（闸门必须复位）", async () => {
  const { state, submitOrder } = makeHarness();
  await submitOrder();
  await submitOrder();
  assert.equal(state.placeOrderCalls.length, 2, "串行两次下单都应成功提交");
  assert.equal(state.successToasts, 2);
  assert.equal(state.reloadCalls, 2);
});

await check("下单失败后闸门同样复位（否则按钮永久失效）", async () => {
  const { state, submitOrder } = makeHarness({ reject: true });
  await submitOrder();
  await submitOrder();
  assert.equal(state.placeOrderCalls.length, 2, "失败后必须允许重试");
  assert.equal(state.successToasts, 0, "失败不应提示成功");
});

// ---------- 回归：原有前置条件仍然生效 ----------
await check("未选股票/账户或表单不合法时不提交（原有校验不回归）", async () => {
  for (const opts of [{ noStock: true }, { noAccount: true }, { canTrade: false }]) {
    const { state, submitOrder } = makeHarness(opts);
    await submitOrder();
    assert.equal(state.placeOrderCalls.length, 0, `不应下单：${JSON.stringify(opts)}`);
  }
});

await check("提交体字段不变（stockId/fundsAccountId/side/price/quantity）", async () => {
  const { state, submitOrder } = makeHarness();
  await submitOrder();
  assert.deepEqual(state.placeOrderCalls[0], {
    stockId: 7,
    fundsAccountId: 3,
    side: "BUY",
    price: "97",
    quantity: "100",
  });
});

// ---------- 结构守卫 ----------
await check("按钮绑定 :loading=\"submitting\"（改前无 loading 状态）", () => {
  assert.match(
    viewSource,
    /:loading="submitting"/,
    "下单按钮必须绑定 :loading=\"submitting\"",
  );
  assert.match(
    viewSource,
    /const submitting = ref\(false\)/,
    "必须声明 submitting 闸门状态",
  );
});

console.log("T-02 下单防连点：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
