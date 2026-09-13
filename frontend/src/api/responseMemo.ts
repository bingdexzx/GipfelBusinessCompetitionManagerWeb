/**
 * 请求层内存 memo（原 request.ts 内联实现抽出，便于单测）。
 *
 * 作用：同一资源在多个组件/多次挂载时，窗口内复用最近一次成功响应，避免重复请求
 * （stale-while-revalidate）。**这份 memo 是模块级共享状态、键不含账号**，因此账号切换
 * （登出 → 换账号登录）必须清空，否则 15s 窗口内新账号会命中上一个账号的响应
 * （例如按 viewCompanyScopes 裁剪过的公司列表）——审计 F-06。
 *
 * 除「登出清空」外还有一个时序漏洞：登出时已发出、尚未返回的请求会在返回后重新写入
 * memo，把刚清掉的旧账号数据又放回来。故写入需要携带发起时的 epoch（见 `memoEpoch()` /
 * `writeMemo()`）：`resetResponseMemo()` 会递增 epoch，旧 epoch 的写入一律丢弃。
 */
export const STALE_WINDOW_MS = 15 * 1000;

/** 资源最近一次实时事件时间的保留上限（防止无界增长）。 */
const MAX_EVENT_ENTRIES = 100;
const EVENT_RETENTION_MS = 3600_000;

let _epoch = 0;
const _memo = new Map<string, { time: number; value: unknown }>();
const _lastEventAt = new Map<string, number>();

/** 当前会话 epoch：请求发起时记录，写回 memo 前比对。 */
export function memoEpoch(): number {
  return _epoch;
}

/** 清空内存 memo（登出 / 换账号 / 清缓存时调用）。 */
export function resetResponseMemo(): void {
  _epoch += 1;
  _memo.clear();
  _lastEventAt.clear();
}

/** 读取某请求键的 memo 条目（无则 undefined）。 */
export function getMemoEntry(key: string): { time: number; value: unknown } | undefined {
  return _memo.get(key);
}

/**
 * 写入 memo 条目；返回是否写入成功。
 *
 * `epoch` 是请求**发起时**的会话 epoch：登出/换账号会递增 epoch，此前的在途请求返回后
 * 不能把上一账号的数据写回 memo（否则清空动作被迟到响应立刻撤销，换账号仍会串档）。
 */
export function writeMemo(
  key: string,
  entry: { time: number; value: unknown },
  epoch: number,
): boolean {
  if (epoch !== _epoch) return false;
  _memo.set(key, entry);
  return true;
}

/** 某资源最近一次实时事件时间（无则 -Infinity）。 */
export function resourceEventAt(resource: string): number {
  return _lastEventAt.get(resource) ?? -Infinity;
}

/** 实时事件到达时调用：标记该资源「最近有变更」，使 memo 立即失效并触发刷新。 */
export function bumpResourceEvent(resource: string): void {
  if (!resource) return;
  _lastEventAt.set(resource, Date.now());
  // 防止无界增长：条目超过上限时清理 1 小时前的旧条目
  if (_lastEventAt.size > MAX_EVENT_ENTRIES) {
    const cutoff = Date.now() - EVENT_RETENTION_MS;
    for (const [k, v] of _lastEventAt) {
      if (v < cutoff) _lastEventAt.delete(k);
    }
  }
}

/** memo 条目是否仍在新鲜度窗口内且未被实时事件作废。 */
export function isMemoFresh(
  entry: { time: number; value: unknown } | undefined,
  resource: string,
  now: number = Date.now(),
): boolean {
  if (!entry) return false;
  return now - entry.time < STALE_WINDOW_MS && resourceEventAt(resource) <= entry.time;
}
