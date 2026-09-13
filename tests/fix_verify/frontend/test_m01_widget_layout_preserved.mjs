/**
 * M-01 验证（数据丢失一半）：仪表盘布局的读写必须**保留**「类型尚未注册」的控件。
 *
 * 背景：控件包要登录后才拉得到（启动时无 token 会 401），而改前 DashboardView.loadWidgets()
 * 会把未注册类型的控件直接 filter 掉，widgets 的 deep watch 随后把裁剪后的列表回写
 * localStorage —— 一次「登录前加载失败」的会话就把用户已保存的自定义布局永久删除。
 * 修复把这段逻辑抽成纯函数（src/components/dashboard/layoutStorage.ts）。
 *
 * 注意：改前不存在该模块（逻辑内联在 DashboardView.vue 内），故本文件只对改后行为做断言；
 * 「改前会话」的行为由 test_m01_widget_packages_reload.mjs 的实测覆盖（登录前未注册）。
 *
 * 用法：
 *   frontend/node_modules/@esbuild/win32-x64/esbuild.exe frontend/src/components/dashboard/layoutStorage.ts --format=esm --outfile=<临时目录>/layoutStorage.mjs
 *   node tests/fix_verify/frontend/test_m01_widget_layout_preserved.mjs <临时目录>/layoutStorage.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_m01_widget_layout_preserved.mjs <构建后的 layoutStorage.mjs 路径>");
  process.exit(2);
}

const { mergeLayoutForSave, migrateLegacySizes, splitStoredLayout } = await import(
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

const known = (t) => t === "text" || t === "demo-gauge";

check("未注册类型的控件在载入→回写往返后仍在（改前被永久删除）", () => {
  const stored = [
    { id: "a", type: "text" },
    { id: "custom", type: "demo-gauge" },
  ];
  const all = splitStoredLayout(stored, known);
  assert.deepEqual(all.visible.map((w) => w.id), ["a", "custom"]);
  assert.equal(all.preserved.length, 0);

  // 控件包未加载：demo-gauge 未注册
  const notLoaded = (t) => t === "text";
  const split = splitStoredLayout(stored, notLoaded);
  assert.deepEqual(split.visible.map((w) => w.id), ["a"]);
  assert.deepEqual(split.preserved.map((w) => w.id), ["custom"]);

  const saved = mergeLayoutForSave(split.visible, split.preserved, split.order);
  assert.deepEqual(
    saved.map((w) => w.id),
    ["a", "custom"],
    "回写不得丢掉未注册类型的控件",
  );
});

check("原存储顺序保持：未注册项夹在中间时不被打乱", () => {
  const stored = [
    { id: "1", type: "text" },
    { id: "2", type: "lost-widget" },
    { id: "3", type: "text" },
    { id: "4", type: "lost-widget-2" },
  ];
  const split = splitStoredLayout(stored, known);
  const saved = mergeLayoutForSave(split.visible, split.preserved, split.order);
  assert.deepEqual(saved.map((w) => w.id), ["1", "2", "3", "4"]);
});

check("已渲染控件取最新状态（位置/配置改动被写入），且不重复", () => {
  const stored = [{ id: "x", type: "demo-gauge" }];
  const split = splitStoredLayout(stored, known);
  const visible = [{ id: "x", type: "demo-gauge", x: 500, config: { custom: { color: "#fff" } } }];
  const saved = mergeLayoutForSave(visible, split.preserved, split.order);
  assert.equal(saved.length, 1, "同 id 的条目不得出现两次");
  assert.equal(saved[0].x, 500);
  assert.deepEqual(saved[0].config, { custom: { color: "#fff" } });
});

check("新增控件追加到末尾；存储里已有的顺序不变", () => {
  const stored = [
    { id: "1", type: "text" },
    { id: "lost", type: "lost-widget" },
  ];
  const split = splitStoredLayout(stored, known);
  const visible = [...split.visible, { id: "new", type: "gauge" }];
  const saved = mergeLayoutForSave(visible, split.preserved, split.order);
  assert.deepEqual(saved.map((w) => w.id), ["1", "lost", "new"]);
});

check("用户在本次会话里删除的控件不再被写回（不能因保留桶而复活）", () => {
  const stored = [
    { id: "1", type: "text" },
    { id: "2", type: "demo-gauge" },
  ];
  const split = splitStoredLayout(stored, known);
  // 用户删除了 id=1
  const saved = mergeLayoutForSave([split.visible[1]], split.preserved, split.order);
  assert.deepEqual(saved.map((w) => w.id), ["2"]);
});

check("旧版布局（单一 size）迁移为 w/h，且不再保留 size 字段", () => {
  const migrated = migrateLegacySizes([{ id: "1", type: "text", size: 180 }]);
  assert.equal(migrated[0].w, 180);
  assert.equal(migrated[0].h, 180);
  assert.ok(!("size" in migrated[0]), "size 字段应被移除（避免写入 undefined）");
  const json = JSON.stringify(migrated);
  assert.ok(!json.includes("size"), `序列化后不应出现 size：${json}`);

  // 已有 w/h 的新版布局原样返回
  const kept = migrateLegacySizes([{ id: "2", type: "text", w: 200, h: 100 }]);
  assert.deepEqual(kept[0], { id: "2", type: "text", w: 200, h: 100 });
});

check("空布局 / 非数组输入不抛错（localStorage 内容损坏时的兜底）", () => {
  assert.deepEqual(migrateLegacySizes(null), []);
  assert.deepEqual(migrateLegacySizes(undefined), []);
  assert.deepEqual(splitStoredLayout([], known), { visible: [], preserved: [], order: [] });
  assert.deepEqual(mergeLayoutForSave([], [], []), []);
});

check("clearAll 语义：保留桶一并清空后，回写结果为空", () => {
  const stored = [
    { id: "1", type: "text" },
    { id: "2", type: "lost-widget" },
  ];
  const split = splitStoredLayout(stored, known);
  assert.deepEqual(split.visible.map((w) => w.id), ["1"]);
  assert.deepEqual(split.preserved.map((w) => w.id), ["2"]);
  // 用户的「清空仪表盘」：widgets = [] 且 preserved = []
  assert.deepEqual(mergeLayoutForSave([], [], []), []);
  // 仅清空 widgets 而忘了保留桶，会把未注册项带回来（故 DashboardView.clearAll 两者都清）
  assert.deepEqual(
    mergeLayoutForSave([], split.preserved, split.order).map((w) => w.id),
    ["2"],
  );
});

console.log("M-01 仪表盘布局保留未注册控件：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
