/**
 * 前端「列表分页」修复的验证（条目 A-01 / V-04 / W-05）。
 *
 * 用 Node 直接跑**构建产物**（由 esbuild 从 frontend/src/api/localPaging.ts 转译而来），
 * 校验的是真实代码，而不是复制一份逻辑。
 *
 * 用法：
 *   node frontend/node_modules/.bin/esbuild frontend/src/api/localPaging.ts \
 *        --format=esm --outfile=<临时目录>/localPaging.mjs
 *   node tests/fix_verify/frontend/test_list_paging.mjs <临时目录>/localPaging.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_list_paging.mjs <构建后的 localPaging.mjs 路径>");
  process.exit(2);
}
const { applyLocalPaging } = await import(pathToFileURL(path.resolve(modulePath)).href);

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

const makeItems = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1 }));

// ---------- 缺陷场景：未传 pageSize 不得静默截断 ----------
check("未传 pageSize：120 条必须全部返回（改前只返回前 50 条）", () => {
  const res = applyLocalPaging(makeItems(120), "paged", { competitionId: 1 });
  assert.equal(res.items.length, 120);
  assert.equal(res.total, 120);
});

check("未传 pageSize：正好 51 条也必须全返回（改前丢 1 条）", () => {
  const res = applyLocalPaging(makeItems(51), "paged", {});
  assert.equal(res.items.length, 51);
  assert.equal(res.items[0].id, 1);
  assert.equal(res.items[50].id, 51);
});

check("未传 pageSize：20 条与空集合边界", () => {
  assert.equal(applyLocalPaging(makeItems(20), "paged", {}).items.length, 20);
  const empty = applyLocalPaging([], "paged", {});
  assert.equal(empty.items.length, 0);
  assert.equal(empty.total, 0);
});

check("未传 pageSize：total 反映全量而非切片长度", () => {
  const res = applyLocalPaging(makeItems(200), "paged", { page: 1 });
  assert.equal(res.total, 200, "total 必须是全量条数（前端「共 N 条」依赖它）");
  assert.equal(res.items.length, 200);
});

// ---------- 功能不变：显式分页参数照旧生效 ----------
check("显式 pageSize：按页切片（第 2 页 20 条/页）", () => {
  const res = applyLocalPaging(makeItems(120), "paged", { page: 2, pageSize: 20 });
  assert.equal(res.items.length, 20);
  assert.equal(res.items[0].id, 21);
  assert.equal(res.total, 120);
  assert.equal(res.page, 2);
  assert.equal(res.pageSize, 20);
});

check("显式 pageSize：末页不足一页时返回剩余条数", () => {
  const res = applyLocalPaging(makeItems(25), "paged", { page: 2, pageSize: 20 });
  assert.equal(res.items.length, 5);
  assert.equal(res.items[0].id, 21);
});

check("显式 pageSize：超出末页返回空数组但 total 不变", () => {
  const res = applyLocalPaging(makeItems(25), "paged", { page: 9, pageSize: 20 });
  assert.equal(res.items.length, 0);
  assert.equal(res.total, 25);
});

check("array 形状（裸数组接口）原样返回，不受分页参数影响", () => {
  const items = makeItems(120);
  assert.equal(applyLocalPaging(items, "array", {}), items);
  assert.equal(applyLocalPaging(items, "array", { page: 2, pageSize: 10 }).length, 120);
});

check("无 pageSize 时返回的 pageSize 与 items 长度自洽", () => {
  const res = applyLocalPaging(makeItems(7), "paged", {});
  assert.equal(res.pageSize, res.items.length > 0 ? res.total : res.pageSize);
  assert.ok(res.pageSize >= res.items.length, "pageSize 不小于本页条数");
});

console.log(cases.join("\n"));
console.log(`\n结果：PASS=${pass} FAIL=${fail}`);
process.exit(fail === 0 ? 0 : 1);
