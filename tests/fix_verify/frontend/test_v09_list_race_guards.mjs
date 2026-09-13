/**
 * V-09 验证：列表加载必须有请求代次守卫，旧响应不得覆盖新数据。
 *
 * 涉及四处（审计 V-09）：MapsManager.loadData、ContractManageView.loadContracts、
 * TechTreeManager.loadData、FuelManager.loadData。它们的 loadData 会被首屏 / 切比赛
 * （useCompetitionReload）/ 实时事件（useResourceChanged）/ 保存后刷新并发触发，
 * 改前直接把响应写回列表：晚到的旧响应会覆盖新数据（切到比赛 B 又跳回 A 的列表），
 * 旧请求的 finally 还会提前关掉 loading。
 *
 * 本文件从各 SFC 抽出真实加载函数（tsc 转译）执行，配合**真实**的 useLatestRequest
 * （esbuild 构建产物）；改前状态下代次桩不会被旧代码引用，故同一套断言可直接跑改前代码。
 *
 * 用法：
 *   frontend/node_modules/@esbuild/win32-x64/esbuild.exe frontend/src/composables/useLatestRequest.ts --bundle --format=esm --platform=browser --outfile=<临时目录>/useLatestRequest.mjs
 *   node tests/fix_verify/frontend/test_v09_list_race_guards.mjs <临时目录>/useLatestRequest.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_v09_list_race_guards.mjs <构建后的 useLatestRequest.mjs 路径>");
  process.exit(2);
}
const { useLatestRequest } = await import(pathToFileURL(path.resolve(modulePath)).href);

const here = path.dirname(fileURLToPath(import.meta.url));
const viewsDir = path.resolve(here, "../../../frontend/src/views/data-management");

const require = createRequire(import.meta.url);
const ts = require(
  path.resolve(here, "../../../frontend/node_modules/typescript/lib/typescript.js"),
);
const transpile = (code) =>
  ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;

/** 抽出 `async function name(...) { ... }`（不做平衡括号解析，靠缩进闭合） */
function extractFn(file, name) {
  const source = fs.readFileSync(path.join(viewsDir, file), "utf8").replace(/\r\n/g, "\n");
  const m = source.match(new RegExp(`async function ${name}\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}`));
  assert.ok(m, `无法从 ${file} 抽取 ${name}（源码结构变了？）`);
  return { source, params: m[1], body: m[2] };
}

/** 通用：造环境 + 可挂起的请求桩 */
function makeHarness(target) {
  const { params, body } = extractFn(target.file, target.fn);
  const calls = [];
  const pending = (url, config) => {
    const call = { url, params: config?.params, index: calls.length };
    calls.push(call);
    return new Promise((resolve, reject) => {
      call.resolve = resolve;
      call.reject = reject;
    });
  };
  const scope = {
    loading: { value: false },
    compStore: { competitionId: 1 },
    console: { error() {}, warn() {}, log() {} },
    api: { get: async (url, config) => pending(url, config) },
    mapsApi: { full: async (config) => pending("maps.full", config) },
    fuelsApi: { list: async (config) => pending("fuels.list", config) },
    contractsApi: { list: async (config) => pending("contracts.list", config) },
    loadRegionsFromServer: async () => {},
    recomputeBBoxIfAuto: () => {},
    nextTick: async () => {},
    renderTree: () => {},
    viewMode: { value: "list" },
    ...target.extraScope(),
  };
  const guard = useLatestRequest();
  scope.nextRequest = guard.next;
  scope.isCurrent = guard.isCurrent;

  const run = new Function(
    ...Object.keys(scope),
    `return ${transpile(`(async (${params}) => {${body}\n})`)}`,
  )(...Object.values(scope));

  return { run, calls, scope };
}

const idOf = (cid, n) => Array.from({ length: n }, (_, i) => `${cid}-${i + 1}`);

const TARGETS = [
  {
    name: "MapsManager.loadData",
    file: "MapsManager.vue",
    fn: "loadData",
    extraScope: () => ({
      nodes: { value: [{ id: "旧节点" }] },
      edges: { value: [] },
      nodeTypes: { value: [] },
      pathTypes: { value: [] },
      regions: { value: [] },
      regionIdMap: { value: new Map() },
    }),
    payload: (cid) => ({ nodes: idOf(cid, 2).map((id) => ({ id })) }),
    read: (h) => h.scope.nodes.value.map((x) => x.id),
  },
  {
    name: "ContractManageView.loadContracts",
    file: "ContractManageView.vue",
    fn: "loadContracts",
    extraScope: () => ({ contracts: { value: [{ id: "旧合同" }] } }),
    payload: (cid) => idOf(cid, 2).map((id) => ({ id })),
    read: (h) => h.scope.contracts.value.map((x) => x.id),
  },
  {
    name: "TechTreeManager.loadData",
    file: "TechTreeManager.vue",
    fn: "loadData",
    extraScope: () => ({ nodes: { value: [{ id: "旧科技" }] } }),
    payload: (cid) => idOf(cid, 2).map((id) => ({ id })),
    read: (h) => h.scope.nodes.value.map((x) => x.id),
  },
  {
    name: "FuelManager.loadData",
    file: "FuelManager.vue",
    fn: "loadData",
    extraScope: () => ({ data: { value: [{ id: "旧燃料" }] } }),
    payload: (cid) => idOf(cid, 2).map((id) => ({ id })),
    read: (h) => h.scope.data.value.map((x) => x.id),
  },
];

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

for (const t of TARGETS) {
  await check(`${t.name}：单次请求正常写回（不回归）`, async () => {
    const h = makeHarness(t);
    const p = h.run();
    h.calls[0].resolve(t.payload(1));
    await p;
    assert.deepEqual(t.read(h), idOf(1, 2));
    assert.equal(h.scope.loading.value, false);
  });

  await check(`${t.name}：切比赛后旧响应晚到，不得覆盖新数据`, async () => {
    const h = makeHarness(t);
    const first = h.run(); // 比赛 1 的请求
    h.scope.compStore.competitionId = 2;
    const second = h.run(); // 切到比赛 2
    h.calls[1].resolve(t.payload(2));
    await second;
    h.calls[0].resolve(t.payload(1)); // 比赛 1 的响应姗姗来迟
    await first;
    assert.deepEqual(
      t.read(h),
      idOf(2, 2),
      `晚到的旧响应不得覆盖新数据，实际 ${JSON.stringify(t.read(h))}`,
    );
  });

  await check(`${t.name}：过时请求不得提前关闭 loading`, async () => {
    const h = makeHarness(t);
    const first = h.run();
    const second = h.run();
    h.calls[0].resolve(t.payload(1));
    await first;
    assert.equal(h.scope.loading.value, true, "旧请求返回后 loading 应保持 true");
    h.calls[1].resolve(t.payload(1));
    await second;
    assert.equal(h.scope.loading.value, false);
  });

  await check(`${t.name}：未选择比赛时清空列表且不发请求（不回归）`, async () => {
    const h = makeHarness(t);
    h.scope.compStore.competitionId = null;
    await h.run();
    assert.equal(h.calls.length, 0);
    assert.equal(h.scope.loading.value, false);
  });
}

await check("源码守卫：四处加载函数都接入了 useLatestRequest", () => {
  for (const t of TARGETS) {
    const { source, body } = extractFn(t.file, t.fn);
    assert.match(source, /useLatestRequest/, `${t.file} 必须引入 useLatestRequest`);
    assert.match(body, /const token = nextRequest\(\)/, `${t.fn} 必须记录请求代次`);
    assert.match(body, /if \(!isCurrent\(token\)\) return;/, `${t.fn} 写回前必须校验代次`);
  }
});

console.log("V-09 列表并发请求守卫：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
