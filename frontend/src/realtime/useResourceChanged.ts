// 兼容旧组件：useResourceChanged(resource, onChanged, options?)
// 适配重写后的 realtime 层（onResourceChanged 基于 socket 直发）。
import { onUnmounted } from "vue";
import { onResourceChanged } from "./resource-changed";
import { useCompetitionStore } from "@/stores/competition";

export interface ResourceChangedDetail {
  resource?: string;
  id?: number | null;
  ids?: number[];
  action?: string;
  competitionId?: number | null;
  seq?: number | null;
  ts?: number | null;
}

export interface UseResourceChangedOptions {
  scope?: "competition" | "global" | "any";
}

/**
 * 订阅资源变更事件，收到匹配事件时调用 onChanged。
 * @param resource 资源名（与后端 MODEL_TO_RESOURCE 一致）
 * @param onChanged 回调（通常为重新加载列表）
 * @param options.scope 匹配范围，默认 "competition"
 */
export function useResourceChanged(
  resource: string,
  onChanged: (detail?: ResourceChangedDetail) => void,
  options?: UseResourceChangedOptions,
) {
  const scope = options?.scope ?? "competition";
  const compStore = useCompetitionStore();

  const handler = (e: any) => {
    if (!e || e.resource !== resource) return;
    // 批量事件一律触发
    if (e.action === "bulk") {
      onChanged(e);
      return;
    }
    if (scope === "any") {
      onChanged(e);
      return;
    }
    const currentCid = compStore.competitionId;
    const eventCid = e.competitionId;
    if (scope === "global") {
      if (eventCid == null) onChanged(e);
      return;
    }
    // competition
    if (eventCid != null && currentCid != null && eventCid === currentCid) {
      onChanged(e);
    }
  };

  const off = onResourceChanged(resource, handler);
  onUnmounted(() => off());
}
