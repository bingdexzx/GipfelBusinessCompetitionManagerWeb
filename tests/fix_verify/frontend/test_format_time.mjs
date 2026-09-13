/**
 * formatTime 时区口径的验证（条目 F-08）。
 *
 * 强制 TZ=Asia/Shanghai（后端 TIME_ZONE 亦为 Asia/Shanghai），使断言与运行机器无关。
 *
 *   frontend/node_modules/.bin/esbuild frontend/src/utils/format.ts \
 *       --format=esm --outfile=tests/fix_verify/frontend/.build/format.mjs
 *   node tests/fix_verify/frontend/test_format_time.mjs tests/fix_verify/frontend/.build/format.mjs
 */
process.env.TZ = "Asia/Shanghai";

import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_format_time.mjs <构建后的 format.mjs 路径>");
  process.exit(2);
}
const { formatTime } = await import(pathToFileURL(path.resolve(modulePath)).href);

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

// ---------- 缺陷场景：UTC 输入必须按本地（Asia/Shanghai）显示 ----------
check("UTC 零点 → 本地 08:00（改前显示 00:00，全站时间少 8 小时）", () => {
  assert.equal(formatTime("2026-09-13T00:00:00Z"), "2026-09-13 08:00:00");
});

check("带 +08:00 偏移的 ISO 串 → 按同一时刻显示（改前会再减 8 小时）", () => {
  assert.equal(formatTime("2026-09-13T18:30:45+08:00"), "2026-09-13 18:30:45");
});

check("跨日边界：UTC 16:00 → 本地次日 00:00", () => {
  assert.equal(formatTime("2026-09-13T16:00:00Z"), "2026-09-14 00:00:00");
});

check("年末边界：UTC 2026-12-31T16:00Z → 本地 2027-01-01 00:00", () => {
  assert.equal(formatTime("2026-12-31T16:00:00Z"), "2027-01-01 00:00:00");
});

check("Date 对象同样按本地时间渲染（不再走 toISOString）", () => {
  const d = new Date("2026-09-13T00:00:00Z");
  assert.equal(formatTime(d), "2026-09-13 08:00:00");
});

check("月末/闰年边界：2028-02-29T20:00Z → 本地 2028-03-01 04:00", () => {
  assert.equal(formatTime("2028-02-29T20:00:00Z"), "2028-03-01 04:00:00");
});

// ---------- 功能不变 ----------
check("空值/非法输入仍返回 '-'", () => {
  assert.equal(formatTime(null), "-");
  assert.equal(formatTime(undefined), "-");
  assert.equal(formatTime(""), "-");
  assert.equal(formatTime("not-a-date"), "-");
});

check("输出格式仍为 YYYY-MM-DD HH:mm:ss（19 字符、无毫秒、无 T）", () => {
  const s = formatTime("2026-09-13T08:00:00.123456+08:00");
  assert.equal(s.length, 19);
  assert.ok(!s.includes("T"));
  assert.ok(!s.includes("."));
  assert.match(s, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
});

check("补零正确（个位数月/日/时/分/秒）", () => {
  assert.equal(formatTime("2026-01-02T00:03:04Z"), "2026-01-02 08:03:04");
});

console.log(cases.join("\n"));
console.log(`\n结果：PASS=${pass} FAIL=${fail}`);
process.exitCode = fail === 0 ? 0 : 1;
