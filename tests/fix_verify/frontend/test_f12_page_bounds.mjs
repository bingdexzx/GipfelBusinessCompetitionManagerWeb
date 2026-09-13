/**
 * F-12 验证：本地分页参数（page / pageSize）必须收敛到合法范围。
 *
 * 改前 `applyLocalPaging` 直接 `parseInt(String(params.page))`：调用方透传 `?page=0` /
 * `?page=-1` / `?page=abc` / `?pageSize=0` 时 `start` 变成负数或 NaN，`items.slice()` 会
 * 返回空数组或「从末尾倒着取一页」，而 `total` 仍是真实条数 —— 列表显示「暂无数据」
 * 却「共 N 条」，且不抛异常（静默错误数据）。
 *
 * 跑的是真实模块 src/api/localPaging.ts（改前/改后同一套断言）。
 *
 * 用法：
 *   frontend/node_modules/@esbuild/win32-x64/esbuild.exe frontend/src/api/localPaging.ts --format=esm --outfile=<临时目录>/localPaging.mjs
 *   node tests/fix_verify/frontend/test_f12_page_bounds.mjs <临时目录>/localPaging.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_f12_page_bounds.mjs <构建后的 localPaging.mjs 路径>");
  process.exit(2);
}
const { applyLocalPaging } = await import(pathToFileURL(path.resolve(modulePath)).href);

const makeItems = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }));
const paged = (n, params) => applyLocalPaging(makeItems(n), "paged", params);

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

// ---------- 缺陷场景：非法 page ----------
check("page=0 → 按第 1 页返回全量（改前返回空数组但 total=120）", () => {
  const res = paged(120, { page: 0 });
  assert.equal(res.items.length, 120, `空/错页：实际 ${res.items.length} 条`);
  assert.equal(res.items[0].id, 1);
  assert.equal(res.page, 1);
  assert.equal(res.total, 120);
});

check("page=-1 → 按第 1 页返回，不得倒着取末尾一页（改前返回末页）", () => {
  const res = paged(120, { page: -1, pageSize: 50 });
  assert.equal(res.page, 1);
  assert.equal(res.items.length, 50);
  assert.equal(res.items[0].id, 1, "必须从第一条开始，而不是越界读到末尾");
});

check("page 非数字（abc / 空串）→ 第 1 页（改前 slice(NaN,NaN) 返回空数组）", () => {
  for (const bad of ["abc", "", " ", null, undefined, {}, []]) {
    const res = paged(30, { page: bad, pageSize: 10 });
    assert.equal(res.page, 1, `page=${JSON.stringify(bad)}`);
    assert.equal(res.items.length, 10, `page=${JSON.stringify(bad)} 实际 ${res.items.length} 条`);
    assert.equal(res.items[0].id, 1);
  }
});

check("page 为 Infinity/NaN/小数 → 收敛为合法整数页", () => {
  assert.equal(paged(30, { page: Infinity, pageSize: 10 }).page, 1);
  assert.equal(paged(30, { page: NaN, pageSize: 10 }).page, 1);
  const half = paged(30, { page: 1.9, pageSize: 10 });
  assert.equal(half.page, 1);
  assert.equal(half.items[0].id, 1);
});

// ---------- 缺陷场景：非法 pageSize ----------
check("pageSize=0 → 退回全量（改前 slice(0,0) 返回空数组）", () => {
  const res = paged(120, { page: 1, pageSize: 0 });
  assert.equal(res.items.length, 120, `实际 ${res.items.length} 条`);
  assert.equal(res.pageSize, 120);
});

check("pageSize 负数 / 非数字 → 退回全量", () => {
  for (const bad of [-5, "abc", "", null, undefined, {}, NaN]) {
    const res = paged(40, { page: 1, pageSize: bad });
    assert.equal(res.items.length, 40, `pageSize=${JSON.stringify(bad)} 实际 ${res.items.length} 条`);
    assert.equal(res.pageSize, 40);
  }
});

check("pageSize 超上限 → 夹紧到 10000（避免超大值透传）", () => {
  const res = paged(120, { page: 1, pageSize: 999999 });
  assert.equal(res.pageSize, 10000);
  assert.equal(res.items.length, 120);
});

check("pageSize 小数 → 取下整（10.7 → 10）", () => {
  const res = paged(50, { page: 1, pageSize: 10.7 });
  assert.equal(res.pageSize, 10);
  assert.equal(res.items.length, 10);
});

// ---------- 回归：合法分页参数行为不变 ----------
check("合法参数（page=2, pageSize=20）切片与字段不变", () => {
  const res = paged(120, { page: 2, pageSize: 20 });
  assert.equal(res.items.length, 20);
  assert.equal(res.items[0].id, 21);
  assert.equal(res.total, 120);
  assert.equal(res.page, 2);
  assert.equal(res.pageSize, 20);
});

check("合法参数：末页不足一页 / 超出末页空数组但 total 不变", () => {
  const last = paged(25, { page: 2, pageSize: 20 });
  assert.equal(last.items.length, 5);
  assert.equal(last.items[0].id, 21);
  const beyond = paged(25, { page: 9, pageSize: 20 });
  assert.equal(beyond.items.length, 0);
  assert.equal(beyond.total, 25);
});

check("字符串数字参数（/?page=2&pageSize=20 透传）与数字等价", () => {
  const res = paged(120, { page: "2", pageSize: "20" });
  assert.equal(res.page, 2);
  assert.equal(res.pageSize, 20);
  assert.equal(res.items[0].id, 21);
});

check("未传分页参数：全量返回、total 一致（A-01 行为不回归）", () => {
  const res = paged(120, {});
  assert.equal(res.items.length, 120);
  assert.equal(res.total, 120);
  assert.equal(res.page, 1);
});

check("array 形状不受分页参数影响", () => {
  const items = makeItems(120);
  assert.equal(applyLocalPaging(items, "array", { page: 0, pageSize: 0 }), items);
});

console.log("F-12 分页参数边界：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
