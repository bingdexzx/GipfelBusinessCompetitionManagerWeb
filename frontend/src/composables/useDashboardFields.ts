import { ref, computed, watch } from "vue";
import { regionsApi, companiesApi, companyFieldsApi, consumerDemandsApi } from "@/api";
import { extractItems } from "@/api/cache";
import { useCompetitionStore } from "@/stores/competition";
import { useAuthStore } from "@/stores/auth";
import type { FieldRef } from "@/types/dashboard";

export interface SelectableField {
  ref: FieldRef;
  key: string;
  label: string;
  group: "区域总览" | "公司" | "消费者需求";
  fieldType?: string;
  value: unknown;
}

function refKey(ref: FieldRef): string {
  if (ref.source === "region") return `region:${ref.region}:${ref.cardId}`;
  if (ref.source === "demand") return `demand:${ref.region}:${ref.demandId}`;
  return `company:${ref.companyId}:${ref.fieldId}`;
}

/**
 * 聚合「当前账号可查看的所有字段」，供仪表盘控件绑定：
 *  - 区域总览字段：来自地图区域总览卡片（公开可读，需有区域查看权限或超管）。
 *  - 公司字段：服务端 `companiesApi.list` 已按 viewCompanyScopes 过滤可见公司，
 *    再逐个拉取该公司产业字段（范围外公司不在列表内，不会触发 403 降级）。
 * 纯客户端聚合，无需新增后端接口。
 */
export function useDashboardFields() {
  const compStore = useCompetitionStore();
  const authStore = useAuthStore();
  const fields = ref<SelectableField[]>([]);
  const loading = ref(false);

  async function load() {
    const compId = compStore.competitionId ?? undefined;
    loading.value = true;
    try {
      const result: SelectableField[] = [];

      const canRegion =
        authStore.isSuperAdmin ||
        authStore.canAny(["data:region:view", "data:region:edit"]);
      if (canRegion && compId != null) {
        try {
          const regions: any[] = (await regionsApi.mapOverview(compId)) || [];
          for (const r of regions) {
            const cards: any[] = r.cards || [];
            for (const c of cards) {
              const ref: FieldRef = {
                source: "region",
                region: r.region,
                cardId: c.id,
              };
              result.push({
                ref,
                key: refKey(ref),
                label: `${r.region} / ${c.displayName}`,
                group: "区域总览",
                fieldType: c.fieldType,
                value: c.value,
              });
            }
          }
        } catch {
          /* 区域总览读取失败不影响公司字段 */
        }
      }

      // 消费者需求（来自「区域总览」页的消费者需求块）：与区域总览卡片同属区域数据，
      // 后端 GET /consumer-demands 需 data:region:view（超管恒可）；无权限则不纳入仪表盘
      // 字段，避免 PLAYER 等无区域权限账号登录仪表盘触发 403 噪音日志。
      if (canRegion && compId != null) {
        try {
          const demands: any[] = (await consumerDemandsApi.list(compId)) || [];
          for (const d of demands) {
            const ref: FieldRef = {
              source: "demand",
              region: d.region,
              demandId: d.id,
            };
            result.push({
              ref,
              key: refKey(ref),
              label: `${d.region} / ${d.productType} 需求`,
              group: "消费者需求",
              fieldType: "NUMBER",
              value: d.quantity,
            });
          }
        } catch {
          /* 消费者需求读取失败不影响其他字段 */
        }
      }

      const canCompany =
        authStore.isSuperAdmin || authStore.can("company:view");
      if (compId != null && canCompany) {
        try {
          const compRes: any = await companiesApi.list({ competitionId: compId });
          const companies: any[] = extractItems(compRes)?.items ?? compRes?.data ?? [];
          // 并行拉取所有公司字段，避免 N+1 串行请求
          const fieldResults = await Promise.allSettled(
            companies.map((comp: any) => companyFieldsApi.get(comp.id)),
          );
          for (let i = 0; i < companies.length; i++) {
            const comp = companies[i];
            const fieldResult = fieldResults[i];
            if (fieldResult.status !== "fulfilled") continue;
            const fRes: any = fieldResult.value;
            const flds: any[] = fRes?.fields || [];
            for (const f of flds) {
              if (f.visible === false) continue; // 隐藏字段不出现在仪表盘字段选择中
              const ref: FieldRef = {
                source: "company",
                companyId: comp.id,
                fieldId: f.id,
                fieldKey: f.fieldKey,
              };
              result.push({
                ref,
                key: refKey(ref),
                label: `${comp.name} / ${f.name}`,
                group: "公司",
                fieldType: f.fieldType,
                value: f.value,
              });
            }
          }
        } catch {
          /* 无 company:view 或无可见公司时列表为空 */
        }
      }

      fields.value = result;
    } finally {
      loading.value = false;
    }
  }

  const fieldMap = computed(() => {
    const m = new Map<string, SelectableField>();
    for (const f of fields.value) m.set(f.key, f);
    return m;
  });

  function valueOf(ref?: FieldRef): unknown {
    if (!ref) return undefined;
    return fieldMap.value.get(refKey(ref))?.value;
  }

  // 同时监听「登录态是否就绪」：authStore.user 初始为 null，需等 fetchProfile 异步返回后
  // 才有 isSuperAdmin / 权限，进而决定 canRegion / canCompany。若仅在 competitionId 变化时触发，
  // 仪表盘挂载时若 profile 尚未加载，load() 会因权限判定为 false 而拉不到任何字段；
  // 待 profile 就绪后又不再触发，导致首屏空白、必须手动「刷新数据」才出数。
  watch(
    [() => compStore.competitionId, () => authStore.user?.id],
    () => load(),
    { immediate: true },
  );

  return { fields, loading, load, valueOf, refKey };
}
