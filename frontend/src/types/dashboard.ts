/**
 * 字段引用：
 *  - 区域总览卡片以 region+cardId 唯一标识；
 *  - 公司产业字段以 companyId+fieldId 唯一标识；
 *  - 消费者需求以 region+demandId 唯一标识（来自「区域总览」页的消费者需求块）。
 *
 * 此前该类型定义在展示层 `components/dashboard/types.ts` 中，
 * 却被逻辑层 `composables/useDashboardFields.ts` 反向依赖（逻辑层依赖展示层）。
 * 现迁移到公共 types 目录，并由原位置重新导出以保持向后兼容。
 */
export type FieldRef =
  | { source: "region"; region: string; cardId: string }
  | { source: "company"; companyId: number; fieldId: number; fieldKey: string }
  | { source: "demand"; region: string; demandId: number };
