/**
 * W-02 验证（前端侧）：载具「可通过路径类型」的出入参必须用后端契约字段名
 * `vehiclePathTypes: [{ pathTypeId }]`。
 *
 * 改前 VehiclesManager.vue 提交/回填的是 `pathTypeIds`：该字段不在后端
 * `VehicleSerializer` 里，DRF 静默忽略（接口仍返回成功），响应里也没有它 →
 * 勾选的路径类型永远存不进、编辑多选框与详情永远为空。
 *
 * 后端契约侧由 backend/tests_fix_verify/test_w02_vehicle_path_types.py 用真实接口锁定：
 * `{"vehiclePathTypes": [{"pathTypeId": 3}]}` 会落库，`{"pathTypeIds": [3]}` 不会。
 * 本文件断言前端现在产出的 JSON 正是前者。
 *
 * 注意：改前不存在 ./vehiclePathTypes.ts（映射内联在 SFC 里），故本文件只对改后断言；
 * 改前的失效后果由上面的后端契约测试实测（同一请求体 0 行）。
 *
 * 用法：
 *   frontend/node_modules/@esbuild/win32-x64/esbuild.exe frontend/src/views/data-management/vehiclePathTypes.ts --format=esm --outfile=<临时目录>/vehiclePathTypes.mjs
 *   node tests/fix_verify/frontend/test_w02_vehicle_path_types.mjs <临时目录>/vehiclePathTypes.mjs
 */
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const modulePath = process.argv[2];
if (!modulePath) {
  console.error("用法: node test_w02_vehicle_path_types.mjs <构建后的 vehiclePathTypes.mjs 路径>");
  process.exit(2);
}

const { toPathTypeIds, toVehiclePathTypes } = await import(
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

check("提交：路径类型 id 数组 → 后端契约 vehiclePathTypes（改前发的是 pathTypeIds）", () => {
  assert.deepEqual(toVehiclePathTypes([3, 1]), [{ pathTypeId: 3 }, { pathTypeId: 1 }]);
  // 与后端契约测试里手写的请求体完全一致（json 序列化后逐字符相同）
  assert.equal(
    JSON.stringify({ vehiclePathTypes: toVehiclePathTypes([3]) }),
    '{"vehiclePathTypes":[{"pathTypeId":3}]}',
  );
});

check("提交：未选择 → 空数组（后端据此全量替换为空，等于显式清空）", () => {
  assert.deepEqual(toVehiclePathTypes([]), []);
  assert.deepEqual(toVehiclePathTypes(null), []);
  assert.deepEqual(toVehiclePathTypes(undefined), []);
});

check("提交：过滤非法值与重复项（重复会撞唯一约束，后端 500）", () => {
  assert.deepEqual(
    toVehiclePathTypes([2, 2, 0, -1, 3, Number.NaN, 1.5, 4]),
    [{ pathTypeId: 2 }, { pathTypeId: 3 }, { pathTypeId: 4 }],
  );
});

check("回填：后端返回的 vehiclePathTypes → 多选框的 id 数组", () => {
  const row = {
    vehiclePathTypes: [
      { vehicleId: 9, pathTypeId: 5, pathType: { id: 5, name: "公路" } },
      { vehicleId: 9, pathTypeId: 7, pathType: { id: 7, name: "铁路" } },
    ],
  };
  assert.deepEqual(toPathTypeIds(row), [5, 7]);
});

check("回填：兼容只给 pathType.id 的返回；无关联 → 空数组", () => {
  assert.deepEqual(toPathTypeIds({ vehiclePathTypes: [{ pathType: { id: 8 } }] }), [8]);
  assert.deepEqual(toPathTypeIds({ vehiclePathTypes: [] }), []);
  assert.deepEqual(toPathTypeIds({}), []);
  assert.deepEqual(toPathTypeIds(null), []);
});

check("回填：旧字段 pathTypeIds 不再被读取（后端从不返回它，误读会掩盖契约漂移）", () => {
  assert.deepEqual(toPathTypeIds({ pathTypeIds: [1, 2] }), []);
});

check("往返一致：提交后回读得到同一组 id（含顺序）", () => {
  const ids = [9, 4, 11];
  assert.deepEqual(toPathTypeIds({ vehiclePathTypes: toVehiclePathTypes(ids) }), ids);
});

// ---------- 视图接线守卫（改前这一半是缺陷本体：SFC 直接发/读 pathTypeIds）----------
// 提交体与回填都在 SFC 内部，Node 侧无法挂载组件，故用源码级断言守住「必须经映射函数出入」。
const fs = await import("node:fs");
const viewPath = path.resolve(
  path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")),
  "../../../frontend/src/views/data-management/VehiclesManager.vue",
);
const viewSource = fs.readFileSync(viewPath, "utf8");

check("视图提交体使用后端契约字段 vehiclePathTypes（改前是 pathTypeIds）", () => {
  assert.match(
    viewSource,
    /vehiclePathTypes:\s*toVehiclePathTypes\(form\.pathTypeIds\)/,
    "提交体必须写 vehiclePathTypes: toVehiclePathTypes(...)",
  );
  assert.doesNotMatch(
    viewSource,
    /pathTypeIds:\s*form\.pathTypeIds/,
    "不得再提交后端不认识的 pathTypeIds（DRF 静默忽略 → 数据永远存不进）",
  );
});

check("视图回填/回显读取后端返回的 vehiclePathTypes（改前读 row.pathTypeIds）", () => {
  assert.match(
    viewSource,
    /form\.pathTypeIds\s*=\s*toPathTypeIds\(row\)/,
    "编辑弹窗回填必须走 toPathTypeIds(row)",
  );
  assert.match(
    viewSource,
    /toPathTypeIds\(detailData\.value\)/,
    "详情回显必须走 toPathTypeIds(...)",
  );
  assert.doesNotMatch(
    viewSource,
    /(row|detailData)\.pathTypeIds/,
    "不得再读后端从不返回的 pathTypeIds（否则界面永远为空）",
  );
});

console.log("W-02 载具可通过路径类型字段对齐：");
for (const c of cases) console.log(c);
console.log(`  通过 ${pass} / 失败 ${fail}`);
process.exitCode = fail > 0 ? 1 : 0;
