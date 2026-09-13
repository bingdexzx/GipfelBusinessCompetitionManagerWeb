/**
 * 响应体解释的验证（条目 F-01）。
 *
 * 直接跑 esbuild 转译后的真实产物：
 *   frontend/node_modules/.bin/esbuild frontend/src/api/envelope.ts \
 *       --format=esm --outfile=tests/fix_verify/frontend/.build/envelope.mjs
 *   node tests/fix_verify/frontend/test_response_envelope.mjs tests/fix_verify/frontend/.build/envelope.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_response_envelope.mjs <构建后的 envelope.mjs 路径>");
  process.exit(2);
}
const { interpretResponse, isBinaryPayload, isApiEnvelope } = await import(
  pathToFileURL(path.resolve(modulePath)).href
);

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

// ---------- 缺陷场景：文件下载（blob）不得被判为失败 ----------
check("Blob 响应 → binary（改前会因 code===undefined 判为 error）", () => {
  const blob = new Blob(["id,name\n1,x"], { type: "text/csv" });
  const r = interpretResponse(blob);
  assert.equal(r.kind, "binary");
  assert.equal(r.value, blob);
});

check("Blob 空文件（0 字节）同样是 binary", () => {
  const blob = new Blob([], { type: "application/json" });
  assert.equal(interpretResponse(blob).kind, "binary");
});

check("ArrayBuffer / TypedArray 同样按 binary 处理", () => {
  const buf = new ArrayBuffer(8);
  assert.equal(interpretResponse(buf).kind, "binary");
  assert.equal(interpretResponse(new Uint8Array([1, 2, 3])).kind, "binary");
});

check("类 Blob 鸭子类型（跨 realm / 老浏览器）也被识别", () => {
  const fakeBlob = { size: 12, type: "application/octet-stream", slice: () => fakeBlob };
  assert.equal(isBinaryPayload(fakeBlob), true);
  assert.equal(interpretResponse(fakeBlob).kind, "binary");
});

// ---------- 缺陷场景：其它非信封 2xx 也不该被判失败 ----------
check("非信封对象（如 {items:[...]}）→ 原样返回，不再报错", () => {
  const payload = { items: [1, 2], total: 2 };
  const r = interpretResponse(payload);
  assert.equal(r.kind, "data");
  assert.deepEqual(r.value, payload);
});

check("非信封数组 / 字符串 / 数字 / null → 原样返回", () => {
  const arr = [1, 2, 3];
  assert.deepEqual(interpretResponse(arr), { kind: "data", value: arr });
  assert.deepEqual(interpretResponse("OK"), { kind: "data", value: "OK" });
  assert.deepEqual(interpretResponse(0), { kind: "data", value: 0 });
  assert.deepEqual(interpretResponse(null), { kind: "data", value: null });
  assert.deepEqual(interpretResponse(undefined), { kind: "data", value: undefined });
});

// ---------- 功能不变：统一信封语义照旧 ----------
check("信封 code=0 → 返回 data", () => {
  const r = interpretResponse({ code: 0, message: "成功", data: { id: 1 } });
  assert.deepEqual(r, { kind: "data", value: { id: 1 } });
});

check("信封 code=0 且 data 为 null → 返回 null", () => {
  assert.deepEqual(interpretResponse({ code: 0, message: "成功", data: null }), {
    kind: "data",
    value: null,
  });
});

check("信封 code!=0 → error 且带后端 message", () => {
  const r = interpretResponse({ code: 403, message: "没有权限执行此操作", data: null });
  assert.equal(r.kind, "error");
  assert.equal(r.message, "没有权限执行此操作");
});

check("信封 code!=0 但 message 缺失/非字符串 → 兜底「请求失败」", () => {
  assert.equal(interpretResponse({ code: 500, message: null, data: null }).message, "请求失败");
  assert.equal(interpretResponse({ code: 500, data: null }).message, "请求失败");
  assert.equal(interpretResponse({ code: 500, message: "", data: null }).message, "请求失败");
});

check("信封判定：三键齐全才算信封（业务字段恰好叫 code 的对象不算）", () => {
  assert.equal(isApiEnvelope({ code: "SH600000", name: "浦发银行" }), false);
  assert.equal(isApiEnvelope({ code: 0, message: "成功", data: null }), true);
  assert.equal(isApiEnvelope(null), false);
  assert.equal(isApiEnvelope([1, 2]), false);
});

console.log(cases.join("\n"));
console.log(`\n结果：PASS=${pass} FAIL=${fail}`);
process.exitCode = fail === 0 ? 0 : 1;
