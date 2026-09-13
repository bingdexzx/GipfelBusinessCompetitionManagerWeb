/**
 * M-01 验证：登录成功后必须重新拉取控件包，自定义控件才会注册；
 * 注册完成后要通知仪表盘重读本地布局（否则本次会话看不到已保存的自定义控件）。
 *
 * 跑的是**真实模块**：@/api（axios 实例 + 拦截器）、@/stores/auth（真实 login）、
 * @/components/dashboard/registerCustomWidgets（含导入时的那次启动加载）。
 * 只有 axios adapter 与 document 被替换（见 stubs/browser.mjs、entries/m01_boot.mjs）。
 *
 * 用法：
 *   powershell -File tests/fix_verify/frontend/bundle.ps1 -Entry tests/fix_verify/frontend/entries/m01_entry.mjs -Outfile tests/fix_verify/frontend/.build/m01.mjs
 *   node tests/fix_verify/frontend/test_m01_widget_packages_reload.mjs tests/fix_verify/frontend/.build/m01.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_m01_widget_packages_reload.mjs <构建后的 m01.mjs 路径>");
  process.exit(2);
}

const mod = await import(pathToFileURL(path.resolve(modulePath)).href);
const {
  browserStub,
  createPinia,
  getCustomWidget,
  isCustomType,
  listCustomWidgets,
  PACKAGE,
  setActivePinia,
  state,
  useAuthStore,
} = mod;

// component.js 「执行」时把自己的组件挂到 window.__widget_module__（真实控件包的约定）
browserStub.onScriptLoad = () => {
  globalThis.window.__widget_module__ = {
    name: "DemoGauge",
    props: ["widget", "values"],
    render: () => null,
  };
};

setActivePinia(createPinia());
const auth = useAuthStore();

/** 注册完成会派发的事件（仪表盘据此重读本地布局） */
let registryEvents = 0;
globalThis.window.addEventListener("widget-registry:changed", () => {
  registryEvents += 1;
});

async function waitFor(predicate, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate() && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 1));
  }
}

let pass = 0;
let fail = 0;
const lines = [];

async function check(name, fn) {
  try {
    await fn();
    lines.push(`  [PASS] ${name}`);
    pass += 1;
  } catch (e) {
    lines.push(`  [FAIL] ${name}: ${e.message.split("\n")[0]}`);
    fail += 1;
  }
}

// 启动阶段的那次请求（导入模块时发起）先等它落定
await waitFor(() => state.listCalls >= 1);

await check("启动阶段（未登录）请求控件包被 401 拒绝，未注册任何自定义控件", () => {
  assert.equal(state.listCalls, 1, `启动应请求一次控件包，实际 ${state.listCalls} 次`);
  assert.equal(listCustomWidgets().length, 0, "未登录时不应注册出自定义控件");
});

await check("登录成功 → 自动重试拉取控件包（改前只试一次，本会话永远没有自定义控件）", async () => {
  const before = state.listCalls;
  await auth.login("u1", "pwd");
  await waitFor(() => state.listCalls > before);

  assert.equal(state.loginCalls, 1, "登录请求应只发一次");
  assert.ok(
    state.listCalls > before,
    `登录后必须重新拉取控件包，实际仍为 ${state.listCalls} 次（改前不重试）`,
  );
});

await check("登录后自定义控件已注册（isCustomType / getCustomWidget 可用）", async () => {
  await auth.login("u1", "pwd");
  await waitFor(() => isCustomType(PACKAGE.widgetType));

  assert.ok(
    isCustomType(PACKAGE.widgetType),
    `登录后 "${PACKAGE.widgetType}" 应已注册，实际未注册`,
  );
  const def = getCustomWidget(PACKAGE.widgetType);
  assert.equal(def.label, PACKAGE.name);
  assert.deepEqual(def.defaultSize, { w: 200, h: 100 });
  assert.deepEqual(
    (def.fieldSlots || []).map((f) => f.key),
    ["value"],
    "manifest.fields 应转为 fieldSlots",
  );
  assert.deepEqual(
    (def.configFields || []).map((f) => f.key),
    ["color"],
    "manifest.configFields 应转为 configFields",
  );
});

await check("注册完成后派发 widget-registry:changed（仪表盘无需刷新即可显示）", async () => {
  await auth.login("u1", "pwd");
  await waitFor(() => registryEvents > 0);

  assert.ok(registryEvents > 0, "注册完成后应派发 widget-registry:changed（改前无此事件）");
});

await check("重复登录不会并发重复拉取（同一时刻只跑一次加载）", async () => {
  const before = state.listCalls;
  await Promise.all([auth.login("u1", "pwd"), auth.login("u1", "pwd")]);
  await waitFor(() => state.listCalls > before);
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(
    state.listCalls,
    before + 1,
    `并发登录只应触发一次控件包拉取，实际新增 ${state.listCalls - before} 次`,
  );
});

auth.logout();

console.log("M-01 登录后重载控件包：");
for (const l of lines) console.log(l);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
