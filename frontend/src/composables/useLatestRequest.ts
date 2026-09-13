import { ref } from "vue";

/**
 * 请求代次守卫：让「最后一次发出的请求」独占写回权，丢弃乱序到达的旧响应。
 *
 * 背景（审计 W-08 / V-09）：各视图的 `loadData()` 直接把 `await api.get(...)` 的结果写进
 * `data.value`，而它同时被 onMounted、useCompetitionReload（切比赛）、useResourceChanged
 * （实时事件）、保存后刷新等多个来源并发触发。网络返回顺序不受控，晚到的旧响应会覆盖新数据
 * （典型：切到比赛 B 后又显示回比赛 A 的列表；旧请求的 finally 还会把 loading 提前关掉）。
 *
 * 用法：
 * ```ts
 * const { next, isCurrent } = useLatestRequest();
 * async function loadData() {
 *   const token = next();          // 每次发起请求都推进代次
 *   const res = await api.get(...);
 *   if (!isCurrent(token)) return; // 期间又发起了新请求 → 本响应作废
 *   data.value = res;
 * }
 * ```
 */
export function useLatestRequest() {
  const seq = ref(0);

  /** 标记「一次新请求开始」，返回本次请求的代次。 */
  function next(): number {
    seq.value += 1;
    return seq.value;
  }

  /** 该代次是否仍是最新的一次请求（否 = 期间已有更新的请求发出，本响应应丢弃）。 */
  function isCurrent(token: number): boolean {
    return token === seq.value;
  }

  return { next, isCurrent };
}
