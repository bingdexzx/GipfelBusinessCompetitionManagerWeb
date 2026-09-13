/**
 * W-03 验证：零件/产品页面的「原料 / 零件 / 科技节点」下拉必须按比赛取数。
 *
 * 改前这四个加载函数发的请求只有 `{ page, pageSize }`，没有 `competitionId`：
 * 超管不受后端 `apply_competition_scope` 过滤 → 下拉里混入其他比赛的实体，
 * 选中后写入本比赛的关联（CASCADE 删除还会连带清掉别比赛的配比）。
 *
 * 这些函数在 SFC 内部，Node 侧无法挂载组件，故本文件从源码里抽出真实函数体，
 * 注入桩（api / compStore / 各 options ref）后执行，检查真实发出的请求参数与选项内容。
 * 改前/改后跑的是同一套断言。
 *
 * 用法：
 *   node tests/fix_verify/frontend/test_w03_option_competition_scope.mjs
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const viewsDir = path.resolve(here, "../../../frontend/src/views/data-management");

// 抽出的函数体是 TypeScript（含 `const res: any` 之类标注），用项目自带 tsc 转译后再执行
const require = createRequire(import.meta.url);
const ts = require(path.resolve(here, "../../../frontend/node_modules/typescript/lib/typescript.js"));

function transpile(code) {
  return ts.transpileModule(code, {
    compilerOptions: { target: ts.ScriptTarget.ES2020 },
  }).outputText;
}

/** 从 SFC 源码抽出 `async function <name>() { ... }` 的函数体 */
function extractFn(source, name, file) {
  const re = new RegExp(`async function ${name}\\(\\) \\{([\\s\\S]*?)\\n\\}`);
  const m = source.match(re);
  if (!m) {
    throw new Error(`无法从 ${file} 抽取 ${name} 的函数体（源码结构变了？）`);
  }
  return m[1];
}

/** 造一个执行环境：记录 api.get 请求，返回按比赛隔离的假数据 */
function makeHarness(fileName, fnName, opts = {}) {
  const source = fs.readFileSync(path.join(viewsDir, fileName), "utf8");
  const body = extractFn(source, fnName, fileName);

  const calls = [];
  const options = { value: opts.initialOptions ?? [] };
  const scope = {
    api: {
      get: async (url, config) => {
        calls.push({ url, params: config?.params });
        const cid = config?.params?.competitionId;
        if (cid == null) {
          // 后端在「未按比赛过滤」时会返回所有比赛的数据（超管场景）
          return [{ id: 901, name: "别比赛实体" }, { id: 902, name: "本比赛实体" }];
        }
        return [{ id: Number(cid) * 10, name: `比赛${cid}实体` }];
      },
    },
    compStore: { competitionId: opts.competitionId === undefined ? 1 : opts.competitionId },
    materialOptions: options,
    partOptions: options,
    techOptions: options,
  };

  const fn = new Function(
    ...Object.keys(scope),
    `return ${transpile(`(async () => {${body}\n})`)}`,
  )(...Object.values(scope));
  return { run: fn, calls, options, scope };
}

const TARGETS = [
  { file: "PartsManager.vue", fn: "loadMaterialOptions", url: "/materials", label: "原料" },
  { file: "PartsManager.vue", fn: "loadTechOptions", url: "/tech-nodes", label: "科技节点" },
  { file: "ProductsManager.vue", fn: "loadPartOptions", url: "/parts", label: "零件" },
  { file: "ProductsManager.vue", fn: "loadTechOptions", url: "/tech-nodes", label: "科技节点" },
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
  await check(`${t.file} ${t.fn}：${t.label}下拉请求带上 competitionId（改前漏带）`, async () => {
    const h = makeHarness(t.file, t.fn, { competitionId: 7 });
    await h.run();
    assert.equal(h.calls.length, 1, "应发起一次选项请求");
    assert.equal(h.calls[0].url, t.url, "请求地址不变");
    assert.equal(
      h.calls[0].params?.competitionId,
      7,
      `选项请求必须带 competitionId，实际 params=${JSON.stringify(h.calls[0].params)}`,
    );
    assert.equal(h.calls[0].params?.page, 1);
    assert.equal(h.calls[0].params?.pageSize, 200, "分页参数不变");
  });

  await check(`${t.file} ${t.fn}：选项内容只含本比赛实体`, async () => {
    const h = makeHarness(t.file, t.fn, { competitionId: 3 });
    await h.run();
    assert.deepEqual(h.options.value, [{ label: "比赛3实体", value: 30 }]);
  });

  await check(`${t.file} ${t.fn}：未选择比赛时不请求、并清空选项（改前会拉全量）`, async () => {
    const h = makeHarness(t.file, t.fn, {
      competitionId: null,
      initialOptions: [{ label: "上一比赛实体", value: 1 }],
    });
    await h.run();
    assert.equal(h.calls.length, 0, "未选比赛不应发请求");
    assert.deepEqual(h.options.value, [], "残留的上一比赛选项必须清空");
  });

  await check(`${t.file} ${t.fn}：切换比赛后重新取数得到新比赛的选项`, async () => {
    const h = makeHarness(t.file, t.fn, { competitionId: 1 });
    await h.run();
    assert.deepEqual(h.options.value.map((o) => o.value), [10]);
    h.scope.compStore.competitionId = 2; // 用户切换比赛，视图会再次调用该函数
    await h.run();
    assert.equal(h.calls[1].params.competitionId, 2);
    assert.deepEqual(h.options.value.map((o) => o.value), [20], "不得残留上一比赛的选项");
  });
}

await check("源码守卫：四个选项加载函数都不得再出现无 competitionId 的裸请求", () => {
  for (const t of TARGETS) {
    const source = fs.readFileSync(path.join(viewsDir, t.file), "utf8");
    const body = extractFn(source, t.fn, t.file);
    assert.match(
      body,
      /competitionId: compStore\.competitionId/,
      `${t.file} ${t.fn} 必须带 competitionId`,
    );
    assert.doesNotMatch(
      body,
      /params: \{ page: 1, pageSize: 200 \}/,
      `${t.file} ${t.fn} 不得再发无 competitionId 的裸请求`,
    );
  }
});

console.log("W-03 选项下拉按比赛隔离：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
