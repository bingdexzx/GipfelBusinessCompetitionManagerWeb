/**
 * V-05 验证：新建合同引用的实体下拉缓存与地图缓存必须随切换比赛失效。
 *
 * 改前 `useCompetitionReload` 的清理回调只清 contracts / contractTypes / companies /
 * industryTypes，而 `entityOptionsMap`（原料/零件/产品/仓库/产线/科技/燃料/载具/地图节点/基建）、
 * `mapNodes` / `mapEdges` / `techNodes` 都带「已加载就跳过」的守卫且从不失效：
 * 切比赛后新建合同仍能选到上一比赛的实体并提交，nodeRoute 的相邻校验还在用旧边表。
 *
 * 这些函数在 SFC 内部，故本文件从源码抽出真实的 `loadEntityOptions` / `loadMapNodes` /
 * `loadTechNodes` 与 `useCompetitionReload` 的清理回调，注入桩后执行（改前/改后同一套断言）。
 *
 * 用法：
 *   node tests/fix_verify/frontend/test_v05_entity_cache_scope.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const viewPath = path.resolve(
  here,
  "../../../frontend/src/views/data-management/ContractManageView.vue",
);
// 统一成 LF，避免 CRLF 影响下面的源码抽取（仓库工作副本是 CRLF）
const source = fs.readFileSync(viewPath, "utf8").replace(/\r\n/g, "\n");

const require = createRequire(import.meta.url);
const ts = require(
  path.resolve(here, "../../../frontend/node_modules/typescript/lib/typescript.js"),
);
const transpile = (code) =>
  ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;

/** 抽取 `async function name(...) { ... }` 的参数表与函数体 */
function extractFn(name) {
  const re = new RegExp(`async function ${name}\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}`);
  const m = source.match(re);
  if (!m) throw new Error(`无法从 ContractManageView.vue 抽取 ${name}（源码结构变了？）`);
  return { params: m[1], body: m[2] };
}

function extractOptionalFn(name) {
  const re = new RegExp(`function ${name}\\(\\) \\{([\\s\\S]*?)\\n\\}`);
  const m = source.match(re);
  return m ? m[1] : null;
}

/** 抽取 useCompetitionReload 的第二个回调（切比赛时的清理体） */
function extractClearCallback() {
  const start = source.indexOf("useCompetitionReload(");
  assert.ok(start >= 0, "找不到 useCompetitionReload 调用");
  const seg = source.slice(start);
  const endMark = "\n  },\n);";
  const end = seg.indexOf(endMark);
  assert.ok(end >= 0, "找不到 useCompetitionReload 的结束位置");
  const idx = seg.lastIndexOf("\n  () => {", end);
  assert.ok(idx >= 0, "找不到清理回调");
  return seg.slice(idx + "\n  () => {".length, end);
}

const CLEAR_BODY = extractClearCallback();
const CLEAR_CACHE_BODY = extractOptionalFn("clearEntityOptionCaches");

/** 造环境：两个比赛的数据可区分（id = 比赛号 * 1000 + 序号） */
function makeHarness(competitionId) {
  const calls = [];
  const scope = {
    contracts: { value: [{}] },
    contractTypes: { value: [{}] },
    companies: { value: [{}] },
    industryTypes: { value: [{}] },
    entityOptionsMap: {},
    entityLoading: {},
    entityEndpoint: {
      MATERIAL: "/materials",
      TECH_NODE: "/tech-nodes",
      MAP_NODE: "/map-nodes",
      INFRASTRUCTURE: "/infrastructures",
    },
    mapNodes: { value: [] },
    mapEdges: { value: [] },
    techNodes: { value: [] },
    compStore: { competitionId },
    api: {
      get: async (url, config) => {
        calls.push({ url, params: config?.params });
        const cid = config?.params?.competitionId ?? -1;
        return [{ id: cid * 1000 + calls.length, name: `比赛${cid}实体` }];
      },
    },
    mapsApi: {
      nodes: {
        list: async (page, size, cid) => {
          calls.push({ url: "/map-nodes", params: { page, pageSize: size, competitionId: cid } });
          return [{ id: cid * 1000 + 1, fromNodeId: 0, toNodeId: 0 }];
        },
      },
      edges: {
        list: async (page, size, cid) => {
          calls.push({ url: "/map-edges", params: { page, pageSize: size, competitionId: cid } });
          return [{ id: cid * 1000 + 2, fromNodeId: cid, toNodeId: cid + 1 }];
        },
      },
    },
  };

  // 清理回调里可能调用 clearEntityOptionCaches()（改后才有）
  scope.clearEntityOptionCaches = CLEAR_CACHE_BODY
    ? new Function(...Object.keys(scope), `return () => {${CLEAR_CACHE_BODY}\n};`)(
        ...Object.values(scope),
      )
    : () => {
        /* 改前不存在 */
      };

  const clearRun = new Function(
    ...Object.keys(scope),
    `return () => {${CLEAR_BODY}\n};`,
  )(...Object.values(scope));

  const build = (name) => {
    const { params, body } = extractFn(name);
    return new Function(
      ...Object.keys(scope),
      `return ${transpile(`(async (${params}) => {${body}\n})`)}`,
    )(...Object.values(scope));
  };

  return {
    scope,
    calls,
    clearRun,
    loadEntityOptions: build("loadEntityOptions"),
    loadMapNodes: build("loadMapNodes"),
    loadTechNodes: build("loadTechNodes"),
    switchCompetition(cid) {
      scope.compStore.competitionId = cid;
      clearRun();
    },
  };
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

await check("首次加载实体下拉：请求带 competitionId，选项为本比赛实体（改前也正确）", async () => {
  const h = makeHarness(1);
  await h.loadEntityOptions("MATERIAL");
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, "/materials");
  assert.equal(h.calls[0].params.competitionId, 1);
  assert.deepEqual(h.scope.entityOptionsMap.MATERIAL.map((x) => x.name), ["比赛1实体"]);
});

await check("切比赛后实体下拉必须重新拉取新比赛数据（改前命中旧缓存，仍是上一比赛实体）", async () => {
  const h = makeHarness(1);
  await h.loadEntityOptions("MATERIAL");
  h.switchCompetition(2);
  await h.loadEntityOptions("MATERIAL");

  assert.equal(h.calls.length, 2, `切比赛后应重新请求，实际共 ${h.calls.length} 次`);
  assert.equal(h.calls[1].params.competitionId, 2);
  assert.deepEqual(
    h.scope.entityOptionsMap.MATERIAL.map((x) => x.name),
    ["比赛2实体"],
    "下拉里不得残留上一比赛的实体（否则可被写成本比赛的关联）",
  );
});

await check("每个实体类型都要失效（原料/基建/科技/地图节点等）", async () => {
  const h = makeHarness(1);
  for (const t of ["MATERIAL", "INFRASTRUCTURE", "TECH_NODE", "MAP_NODE"]) {
    await h.loadEntityOptions(t);
  }
  const before = h.calls.length;
  h.switchCompetition(5);
  for (const t of ["MATERIAL", "INFRASTRUCTURE", "TECH_NODE", "MAP_NODE"]) {
    await h.loadEntityOptions(t);
  }
  assert.equal(h.calls.length - before, 4, `四类实体都应重新拉取，实际新增 ${h.calls.length - before} 次`);
  for (const t of ["MATERIAL", "INFRASTRUCTURE", "TECH_NODE", "MAP_NODE"]) {
    assert.equal(h.scope.entityOptionsMap[t][0].name, "比赛5实体", `${t} 仍是旧比赛数据`);
  }
});

await check("切比赛后地图节点与边表必须重新拉取（nodeRoute 校验不得用旧边表）", async () => {
  const h = makeHarness(1);
  await h.loadMapNodes();
  const edges1 = h.scope.mapEdges.value.map((e) => e.id);
  assert.deepEqual(edges1, [1000 + 2]);

  h.switchCompetition(3);
  await h.loadMapNodes();

  assert.deepEqual(
    h.scope.mapEdges.value.map((e) => e.id),
    [3000 + 2],
    "边表必须是新比赛的（改前因 mapNodes 非空直接 return，仍用旧边表）",
  );
  const edgeCalls = h.calls.filter((c) => c.url === "/map-edges");
  assert.equal(edgeCalls.length, 2, `边表应请求两次，实际 ${edgeCalls.length} 次`);
  assert.equal(edgeCalls[1].params.competitionId, 3);
});

await check("切比赛后科技树节点必须重新拉取（缓存失效）", async () => {
  const h = makeHarness(1);
  await h.loadTechNodes();
  assert.equal(h.calls.filter((c) => c.url === "/tech-nodes").length, 1);
  h.switchCompetition(4);
  await h.loadTechNodes();
  const techCalls = h.calls.filter((c) => c.url === "/tech-nodes");
  assert.equal(
    techCalls.length,
    2,
    `切比赛后科技节点应重新拉取（改前命中旧缓存），实际 ${techCalls.length} 次`,
  );
});

await check("原有清理行为不回归：合同/类型/公司/产业类型仍被清空", async () => {
  const h = makeHarness(1);
  h.switchCompetition(2);
  assert.deepEqual(h.scope.contracts.value, []);
  assert.deepEqual(h.scope.contractTypes.value, []);
  assert.deepEqual(h.scope.companies.value, []);
  assert.deepEqual(h.scope.industryTypes.value, []);
});

await check("源码守卫：清理回调必须失效实体下拉与地图/科技缓存", () => {
  assert.match(
    CLEAR_BODY,
    /clearEntityOptionCaches\(\)/,
    "切比赛的清理回调必须调用 clearEntityOptionCaches()",
  );
  assert.ok(CLEAR_CACHE_BODY, "必须存在 clearEntityOptionCaches()");
  for (const target of ["entityOptionsMap", "mapNodes", "mapEdges", "techNodes"]) {
    assert.match(CLEAR_CACHE_BODY, new RegExp(target), `clearEntityOptionCaches 必须清空 ${target}`);
  }
});

console.log("V-05 切比赛时实体下拉/地图缓存失效：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
