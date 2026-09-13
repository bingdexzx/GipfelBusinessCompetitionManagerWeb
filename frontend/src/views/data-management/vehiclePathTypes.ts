/**
 * 载具「可通过路径类型」的前后端字段映射（审计 W-02）。
 *
 * 后端契约（`backend/apps/vehicles/serializers.py`）：请求与响应都用
 *   `vehiclePathTypes: [{ pathTypeId, pathType? }]`
 * 而改前前端提交/回填的是 `pathTypeIds` —— 该字段不在 `VehicleSerializer` 声明内，
 * DRF 静默忽略：勾选的路径类型一行都不会写进关系表，接口照样返回「已创建/已更新」；
 * 响应里也没有 `pathTypeIds`，于是编辑弹窗多选框永远空白、详情永远显示 `-`。
 *
 * 表单内部仍用「id 数组」表达多选（Element Plus 的 el-select multiple 需要），
 * 出入后端时统一在这里转换，避免字段名再次漂移。
 */

export interface VehiclePathTypeItem {
  pathTypeId?: number;
  pathType?: { id?: number } | null;
}

/** 表单勾选的路径类型 id → 后端契约 `vehiclePathTypes` */
export function toVehiclePathTypes(ids: readonly number[] | null | undefined): { pathTypeId: number }[] {
  if (!Array.isArray(ids)) return [];
  const seen = new Set<number>();
  const out: { pathTypeId: number }[] = [];
  for (const raw of ids) {
    const id = typeof raw === "number" ? raw : Number(raw);
    // 过滤空值/非数字，并按 id 去重：后端 vehicle_path_types 有 (vehicle, pathType) 唯一约束，
    // 重复项会触发 IntegrityError（500）。
    if (!Number.isInteger(id) || id <= 0 || seen.has(id)) continue;
    seen.add(id);
    out.push({ pathTypeId: id });
  }
  return out;
}

/** 后端返回的 `vehiclePathTypes` → 表单勾选的 id 数组（兼容只给 pathType.id 的返回） */
export function toPathTypeIds(
  vehicle: { vehiclePathTypes?: VehiclePathTypeItem[] | null } | null | undefined,
): number[] {
  const list = vehicle?.vehiclePathTypes;
  if (!Array.isArray(list)) return [];
  const seen = new Set<number>();
  const out: number[] = [];
  for (const item of list) {
    const id = typeof item?.pathTypeId === "number" ? item.pathTypeId : item?.pathType?.id;
    if (typeof id !== "number" || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}
