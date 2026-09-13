/**
 * F-06 验证：登出（换账号）必须清空请求层内存 memo，且旧账号的迟到响应不得回填。
 *
 * 跑的是**真实模块**：@/api（axios 实例 + 拦截器）与 @/stores/auth（真实 logout），
 * 由 bundle.ps1 从 frontend/src 打包，Node 侧只把 axios 的 adapter 换成计数器。
 * 无 IndexedDB（见 stubs/browser.mjs）→ 每次 GET 都真实走「网络 → memo 写入」路径。
 *
 * 用法：
 *   powershell -File tests/fix_verify/frontend/bundle.ps1 -Entry tests/fix_verify/frontend/entries/f06_entry.mjs -Outfile tests/fix_verify/frontend/.build/f06.mjs
 *   node tests/fix_verify/frontend/test_f06_logout_clears_memo.mjs tests/fix_verify/frontend/.build/f06.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_f06_logout_clears_memo.mjs <构建后的 f06.mjs 路径>");
  process.exit(2);
}

const mod = await import(pathToFileURL(path.resolve(modulePath)).href);
const {
  api,
  createPinia,
  setActivePinia,
  useAuthStore,
  resetRequestMemo,
  setActiveUser,
  setAccountItem,
} = mod;

setActivePinia(createPinia());
const auth = useAuthStore();

const DATA = {
  1: [{ id: 1, name: "A公司" }],
  2: [{ id: 2, name: "B公司" }],
};

// ---------- axios adapter 计数桩 ----------
let currentUserId = 1;
let calls = [];
let deferNext = false;
let deferredRelease = null;

api.defaults.adapter = (config) => {
  calls.push({
    url: config.url,
    params: config.params,
    auth: config.headers?.Authorization,
  });
  const response = () => ({
    data: { code: 0, message: "ok", data: DATA[currentUserId] },
    status: 200,
    statusText: "OK",
    headers: {},
    config,
  });
  if (deferNext) {
    deferNext = false;
    return new Promise((resolve) => {
      deferredRelease = () => resolve(response());
    });
  }
  return Promise.resolve(response());
};

const COMPANY_URL = "/companies";
const COMPANY_CFG = { params: { competitionId: 1 } };

function loginAs(userId) {
  currentUserId = userId;
  setActiveUser(userId);
  setAccountItem("token", `token-${userId}`);
}

function resetWorld() {
  resetRequestMemo();
  calls = [];
  deferNext = false;
  deferredRelease = null;
  loginAs(1);
}

async function waitForAdapterCall(timeoutMs = 1000) {
  const deadline = Date.now() + timeoutMs;
  while (deferredRelease === null && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 1));
  }
  assert.ok(deferredRelease, "adapter 未被调用（请求未走到网络层）");
}

let pass = 0;
let fail = 0;
const lines = [];

async function check(name, fn) {
  try {
    resetWorld();
    await fn();
    lines.push(`  [PASS] ${name}`);
    pass += 1;
  } catch (e) {
    lines.push(`  [FAIL] ${name}: ${e.message.split("\n")[0]}`);
    fail += 1;
  }
}

// ---------- 缺陷场景 ----------
await check("窗口内同键 GET 命中内存 memo（修复不得把 memo 一并关掉）", async () => {
  const first = await api.get(COMPANY_URL, COMPANY_CFG);
  assert.deepEqual(first, DATA[1]);
  assert.equal(calls.length, 1);

  const second = await api.get(COMPANY_URL, COMPANY_CFG);
  assert.deepEqual(second, DATA[1]);
  assert.equal(calls.length, 1, `窗口内第二次 GET 应命中 memo，实际网络请求 ${calls.length} 次`);
});

await check("登出后换账号：必须重新请求并拿到新账号数据（改前命中上一账号 memo）", async () => {
  await api.get(COMPANY_URL, COMPANY_CFG);
  assert.equal(calls.length, 1);

  auth.logout();
  loginAs(2);

  const afterSwitch = await api.get(COMPANY_URL, COMPANY_CFG);
  assert.equal(
    calls.length,
    2,
    `登出换账号后必须重新请求，实际网络请求 ${calls.length} 次（改前为 1 次，直接复用上一账号响应）`,
  );
  assert.deepEqual(
    afterSwitch,
    DATA[2],
    `换账号后返回的必须是 B 账号数据，实际 ${JSON.stringify(afterSwitch)}`,
  );
});

await check("登出后重新登录同一账号：也必须重新请求（memo 已清）", async () => {
  await api.get(COMPANY_URL, COMPANY_CFG);
  assert.equal(calls.length, 1);

  auth.logout();
  loginAs(1);

  await api.get(COMPANY_URL, COMPANY_CFG);
  assert.equal(calls.length, 2, `登出后应重新请求，实际网络请求 ${calls.length} 次`);
});

await check("登出时仍在飞行中的旧账号响应，返回后不得回填 memo", async () => {
  deferNext = true;
  const inflight = api.get(COMPANY_URL, COMPANY_CFG);
  await waitForAdapterCall();
  assert.equal(calls.length, 1);

  auth.logout();
  loginAs(2);

  deferredRelease();
  await inflight;

  const afterSwitch = await api.get(COMPANY_URL, COMPANY_CFG);
  assert.equal(
    calls.length,
    2,
    `旧账号的迟到响应不得回填 memo，实际换账号后网络请求 ${calls.length} 次（改前为 1 次）`,
  );
  assert.deepEqual(
    afterSwitch,
    DATA[2],
    `换账号后返回的必须是 B 账号数据，实际 ${JSON.stringify(afterSwitch)}`,
  );
});

await check("resetRequestMemo() 仍能清空 memo（抽取到 responseMemo.ts 后的回归）", async () => {
  await api.get(COMPANY_URL, COMPANY_CFG);
  assert.equal(calls.length, 1);

  resetRequestMemo();
  await api.get(COMPANY_URL, COMPANY_CFG);
  assert.equal(calls.length, 2, `resetRequestMemo 后应重新请求，实际 ${calls.length} 次`);
});

console.log("F-06 登出清理内存 memo：");
for (const l of lines) console.log(l);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
