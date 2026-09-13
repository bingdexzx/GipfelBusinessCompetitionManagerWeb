/**
 * T-01 验证：股票下单「预计金额」= 价格 × 数量，整数价 × 整数数量时不得退化成 0.xx。
 *
 * 改前 StockMarketView.vue 里的实现用 `resultStr.slice(0, -totalDecimals)` 取整数部分：
 * 当价格与数量都是整数时 `totalDecimals === 0`，`slice(0, -0)` 等价 `slice(0, 0)` → 整数部分
 * 为空串（兜底成 '0'），小数部分反而取到结果的前两位：97 × 100 显示 0.97，100 × 100 显示 0.1。
 *
 * 改后把计算抽到 src/views/stocks/estAmount.ts，视图只调用它。本文件为了让「改前/改后」都能
 * 跑真实代码：从 SFC 源码里抽出 `const estAmount = computed(() => { ... });` 的函数体，
 * 注入桩 `computed` / `trade` / `computeEstAmount` 后执行 —— 断言的是视图当前真实使用的算法。
 *
 * 用法（第二个参数在改前不存在，缺失时只有模块相关用例会失败，SFC 抽取用例照常运行）：
 *   frontend/node_modules/@esbuild/win32-x64/esbuild.exe frontend/src/views/stocks/estAmount.ts --format=esm --outfile=<临时目录>/estAmount.mjs
 *   node tests/fix_verify/frontend/test_t01_est_amount.mjs <临时目录>/estAmount.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const modulePath = process.argv[2];
const here = path.dirname(fileURLToPath(import.meta.url));
const viewPath = path.resolve(here, "../../../frontend/src/views/stocks/StockMarketView.vue");
const viewSource = fs.readFileSync(viewPath, "utf8");

// 改后模块（改前不存在）
let moduleFn = null;
if (modulePath && fs.existsSync(path.resolve(modulePath))) {
  moduleFn = (await import(pathToFileURL(path.resolve(modulePath)).href)).computeEstAmount;
}

// ---------- 从 SFC 抽取真实的 estAmount 计算体 ----------
const match = viewSource.match(/const estAmount = computed\(\(\) => \{([\s\S]*?)\n\}\);/);
if (!match) {
  console.error("无法从 StockMarketView.vue 抽取 estAmount 计算体（源码结构变了？）");
  process.exit(2);
}
const viewFnFactory = new Function(
  "computed",
  "trade",
  "computeEstAmount",
  `return computed(() => {${match[1]}\n});`,
);

/** 用视图当前算法算一次预计金额 */
function viewEstAmount(price, quantity) {
  const computedStub = (fn) => ({ get value() { return fn(); } });
  const est = viewFnFactory(computedStub, { value: { price, quantity } }, moduleFn ?? (() => NaN));
  return est.value;
}

let pass = 0;
let fail = 0;
const cases = [];

function check(name, fn) {
  try {
    fn();
    cases.push(`  [PASS] ${name}`);
    pass += 1;
  } catch (e) {
    cases.push(`  [FAIL] ${name}: ${e.message.split("\n")[0]}`);
    fail += 1;
  }
}

// ---------- 缺陷场景（改前必失败）----------
check("整数价 × 整数数量：97 × 100 = 9700（改前显示 0.97）", () => {
  assert.equal(viewEstAmount("97", "100"), 9700);
});

check("整数价 × 整数数量：100 × 100 = 10000（改前显示 0.1）", () => {
  assert.equal(viewEstAmount("100", "100"), 10000);
});

check("各位数组合（1×1、7×3、12×12、999×999）都等于精确乘积", () => {
  for (const [p, q] of [["1", "1"], ["7", "3"], ["12", "12"], ["999", "999"]]) {
    assert.equal(viewEstAmount(p, q), Number(p) * Number(q), `${p} × ${q}`);
  }
});

check("大数（20 位整数 × 100）量级正确，不被当成小数", () => {
  const got = viewEstAmount("99999999999999999999", "100");
  assert.ok(got > 1e21, `预计金额量级必须 >1e21，实际 ${got}（改前 0.99）`);
});

// ---------- 回归：小数场景保持改前行为 ----------
check("小数价：97.5 × 100 = 9750（改前也正确，不得回归）", () => {
  assert.equal(viewEstAmount("97.5", "100"), 9750);
});

check("小数数量：100 × 1.5 = 150", () => {
  assert.equal(viewEstAmount("100", "1.5"), 150);
});

check("小数位超过 2 位仍截断到 2 位（既有行为：1.234 × 1 = 1.23）", () => {
  assert.equal(viewEstAmount("1.234", "1"), 1.23);
  assert.equal(viewEstAmount("0.01", "0.01"), 0);
});

check("0.1 × 0.2 = 0.02（改前同样正确）", () => {
  assert.equal(viewEstAmount("0.1", "0.2"), 0.02);
});

check("零值：0 × 100 = 0，不出现 -0 或 NaN", () => {
  assert.equal(viewEstAmount("0", "100"), 0);
  assert.equal(viewEstAmount("", ""), 0);
  assert.ok(!Object.is(viewEstAmount("0", "100"), -0));
});

check("非法输入：非数字 → 0（不抛错）", () => {
  assert.equal(viewEstAmount("abc", "100"), 0);
  assert.equal(viewEstAmount("100", "abc"), 0);
});

// ---------- 结构守卫（改前必失败）----------
check("视图改为调用 ./estAmount.ts 的 computeEstAmount（改前是内联实现）", () => {
  assert.match(
    viewSource,
    /computeEstAmount\(trade\.value\.price,\s*trade\.value\.quantity\)/,
    "estAmount 必须委托给 computeEstAmount",
  );
  assert.doesNotMatch(
    viewSource,
    /slice\(0,\s*-totalDecimals\)/,
    "不得再出现 slice(0, -totalDecimals)（totalDecimals=0 时即 slice(0,0)）",
  );
});

check("抽出的模块与视图算法一致（同一组输入结果相同）", () => {
  assert.ok(moduleFn, "改后应能构建 src/views/stocks/estAmount.ts");
  for (const [p, q] of [["97", "100"], ["97.5", "100"], ["1.234", "1"], ["0.1", "0.2"], ["abc", "1"]]) {
    assert.equal(moduleFn(p, q), viewEstAmount(p, q), `${p} × ${q}`);
  }
});

console.log("T-01 预计金额（价格 × 数量）：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
