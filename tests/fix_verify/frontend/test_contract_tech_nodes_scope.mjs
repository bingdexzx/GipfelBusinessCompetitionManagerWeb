/**
 * W-03（同类相邻缺陷）验证：ContractManageView 的「科技树清单」下拉必须按比赛取数。
 *
 * 该处的 `loadTechNodes()` 与 W-03 的四个下拉是同一类问题——请求只有 `{ page, pageSize }`：
 * 超管不受后端 `apply_competition_scope` 过滤，会把其他比赛的科技节点混进下拉，
 * 选中后写成本合同的引用。
 *
 * 函数在 SFC 内部，故从源码抽出真实函数体（tsc 转译 TS 标注）注入桩执行。
 *
 * 用法：
 *   node tests/fix_verify/frontend/test_contract_tech_nodes_scope.mjs
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
const source = fs.readFileSync(viewPath, "utf8").replace(/\r\n/g, "\n");

const require = createRequire(import.meta.url);
const ts = require(
  path.resolve(here, "../../../frontend/node_modules/typescript/lib/typescript.js"),
);
const transpile = (code) =>
  ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;

const m = source.match(/async function loadTechNodes\(([^)]*)\) \{([\s\S]*?)\n\}/);
assert.ok(m, "无法从 ContractManageView.vue 抽取 loadTechNodes（源码结构变了？）");

function makeHarness(competitionId) {
  const calls = [];
  const scope = {
    techNodes: { value: [] },
    compStore: { competitionId },
    api: {
      get: async (url, config) => {
        calls.push({ url, params: config?.params });
        const cid = config?.params?.competitionId;
        // 未按比赛过滤时后端返回所有比赛的数据（超管场景）
        if (cid == null) {
          return [
            { id: 901, name: "别比赛科技" },
            { id: 902, name: "本比赛科技" },
          ];
        }
        return [{ id: Number(cid) * 10, name: `比赛${cid}科技` }];
      },
    },
  };
  const run = new Function(
    ...Object.keys(scope),
    `return ${transpile(`(async (${m[1]}) => {${m[2]}\n})`)}`,
  )(...Object.values(scope));
  return { run, calls, scope };
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

await check("科技树清单请求带上 competitionId（改前漏带，拉回全比赛节点）", async () => {
  const h = makeHarness(7);
  await h.run();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, "/tech-nodes");
  assert.equal(
    h.calls[0].params.competitionId,
    7,
    `实际 params=${JSON.stringify(h.calls[0].params)}`,
  );
});

await check("下拉内容只含本比赛的科技节点", async () => {
  const h = makeHarness(3);
  await h.run();
  assert.deepEqual(h.scope.techNodes.value, [{ id: 30, name: "比赛3科技" }]);
});

await check("分页循环参数保持（page 从 1 起、pageSize=200）", async () => {
  const h = makeHarness(2);
  const many = Array.from({ length: 200 }, (_, i) => ({ id: i + 1, name: `t${i}` }));
  // 第一页满 200 条 → 应继续请求第二页
  const original = h.scope.compStore.competitionId;
  const scopeApi = h.scope.api;
  void original;
  void scopeApi;
  let pages = 0;
  const h2 = makeHarness(2);
  // 覆盖桩：第一页满页、第二页不足
  h2.scope.api.get = async (url, config) => {
    pages += 1;
    h2.calls.push({ url, params: config?.params });
    return config.params.page === 1 ? many : [{ id: 999, name: "末页" }];
  };
  await h2.run();
  assert.equal(pages, 2, `应翻到第 2 页，实际请求 ${pages} 次`);
  assert.equal(h2.calls[1].params.page, 2);
  assert.equal(h2.calls[1].params.competitionId, 2, "第二页同样要带 competitionId");
  assert.equal(h2.scope.techNodes.value.length, 201);
});

await check("未选择比赛时不请求", async () => {
  const h = makeHarness(null);
  await h.run();
  assert.equal(h.calls.length, 0);
});

await check("源码守卫：不得再出现无 competitionId 的 /tech-nodes 裸请求", () => {
  assert.doesNotMatch(
    m[2],
    /params: \{ page, pageSize: 200 \}/,
    "loadTechNodes 不得再发无 competitionId 的裸请求",
  );
  assert.match(m[2], /competitionId: compStore\.competitionId/);
});

console.log("W-03 同类：合同页科技树清单按比赛取数：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
