// 实时数据同步：后端在单条/批量记录被创建、更新或删除时，通过 WebSocket 广播
// "resource:changed" { resource, id, competitionId, action, seq, ts }。
// 本模块统一处理该事件：
//   1) 删除（action=deleted）：精确从本地全量副本中移除该 id（client/src/api/cache.ts 的
//      removeFullItemByResource），避免触发整表重拉；随后的增量刷新会通过 existingIds 再次确认删除。
//   2) 创建/更新/批量变更：不再作废本地全量副本（保留它，使随后的「增量刷新」生效，仅拉变更数据），
//      直接派发 window 事件通知组件层自动重拉。组件重拉走 cachedApi → 增量模式，仅取回变更行。
// 使用原生 CustomEvent 而非第三方事件总线，零额外依赖。

import { onRealtime, getSocketInstance, updateLastReceivedSeq } from "./socket";
import { removeFullItemByResource, SEG_TO_RESOURCE } from "@/api/cache";
import { reconcileAllIncremental, bumpResourceEvent } from "@/api/request";

let _boundSocket: unknown = null; // 跟踪已绑定的 socket 实例，避免 socket 重建后漏绑
let _lastSeq = 0; // 记录最后收到的事件序号（用于重连补发）

// O4：实时重拉去抖 —— 同一资源在短时间内的多次事件合并为一次 window 广播，
// 避免「批量创建/更新」触发的一连串组件重拉（每次重拉都打后台增量请求）。
const RELOAD_DEBOUNCE_MS = 400;
const _reloadTimers = new Map<string, ReturnType<typeof setTimeout>>();

function scheduleResourceReload(resource: string, detail: Record<string, any>): void {
  const existing = _reloadTimers.get(resource);
  if (existing) clearTimeout(existing);
  _reloadTimers.set(
    resource,
    setTimeout(() => {
      _reloadTimers.delete(resource);
      window.dispatchEvent(new CustomEvent("resource-changed", { detail }));
    }, RELOAD_DEBOUNCE_MS),
  );
}

/** 获取最后收到的事件序号（用于重连补发） */
export function getLastSeq(): number {
  return _lastSeq;
}

/** 注册全局「资源变更」监听（幂等，多次调用只在 socket 实例变化时重新注册）。建议在实时连接建立后调用。 */
export function bindResourceChanged() {
  const currentRef = getSocketInstance();
  if (_boundSocket === currentRef && _boundSocket !== null) return;
  _boundSocket = currentRef;
  onRealtime(
    "resource:changed",
    (payload: {
      resource?: string;
      id?: number;
      action?: string;
      competitionId?: number;
      seq?: number;
      ts?: number;
    }) => {
      if (!payload || typeof payload.resource !== "string") return;

      // 更新最后收到的事件序号
      if (payload.seq && payload.seq > _lastSeq) {
        _lastSeq = payload.seq;
        // 同步到 socket.ts 的 lastReceivedSeq，消除两套 seq 计数器漂移（见 M5 修复说明）。
        updateLastReceivedSeq(payload.seq);
      }

      // 后端广播的 resource 可能是复数（经 Prisma 中间件自动发，如 materials/contracts/stocks）
      // 或单数（各 service 手写，如 region/consumer-demand）。前端本地全量副本键与 memo 键统一用
      // SEG_TO_RESOURCE 映射后的「单数」（material/contract/stock），故删除与 memo 失效必须用归一的单数；
      // 而组件层 useResourceChanged 订阅传的是复数（materials），故派发给组件层的 window 事件保留
      // 后端原值，确保严格相等匹配。
      const singular = SEG_TO_RESOURCE[payload.resource] || payload.resource;
      // 删除：精确移除本地副本中的该条目（用单数前缀，命中 FULL|material| 等）
      if (payload.action === "deleted" && payload.id != null) {
        void removeFullItemByResource(singular, payload.id);
      }
      // O3：标记该资源「最近有变更」，使内存新鲜度窗口 memo 立即失效、触发刷新
      // （用单数，命中 _resourceOf 计算的 memo 键）
      bumpResourceEvent(singular);
      // O4：同一资源短时间内的多次事件合并为一次广播，避免批量变更触发一连串组件重拉
      // 派发保留后端原值，匹配组件 useResourceChanged 订阅的复数 resource
      scheduleResourceReload(payload.resource, {
        resource: payload.resource,
        id: payload.id ?? null,
        action: payload.action ?? "changed",
        competitionId: payload.competitionId ?? null,
        seq: payload.seq ?? null,
        ts: payload.ts ?? null,
      });
    },
  );

  // 公司产业字段写入后实时广播（自定义事件，非标准 resource:changed）。
  // 统一转译为 window 的 resource-changed 事件（resource="company-field"），
  // 使所有消费组件（含参赛队员的公司详情页）都能在本地全量副本上做增量刷新，
  // 不再依赖单一组件自行订阅，避免漏刷。
  onRealtime(
    "company-field:changed",
    (payload: { companyId?: number; competitionId?: number }) => {
      if (!payload || payload.companyId == null) return;
      // 标记变更：请求侧资源名为 "companyField"（与 collectionKey 对齐），事件侧为 "company-field"，
      // 二者都标记，确保两类 memo 都能被绕过。
      bumpResourceEvent("company-field");
      bumpResourceEvent("companyField");
      scheduleResourceReload("company-field", {
        resource: "company-field",
        id: payload.companyId,
        action: "updated",
        competitionId: payload.competitionId ?? null,
      });
    },
  );

  // 权限变更事件：定向推送到具体用户
  // 前端订阅后拉取 /auth/me 刷新权限状态
  onRealtime(
    "permissions:changed",
    (payload: { userId?: number; version?: number }) => {
      if (!payload || !payload.userId) return;
      // 派发 window 事件通知 auth store 刷新
      window.dispatchEvent(
        new CustomEvent("permissions-changed", {
          detail: { userId: payload.userId, version: payload.version },
        }),
      );
    },
  );

  // 重连补发结果处理
  onRealtime(
    "sync:replay:result",
    (payload: { events?: Array<{ event: string; data: any; ts: number }>; serverSeq?: number }) => {
      if (!payload || !Array.isArray(payload.events)) return;
      // 服务端序号回退检测：若 serverSeq 小于本端记录的 _lastSeq，说明服务端重启过、
      // 内存序号与缓冲已归零，基于旧 _lastSeq 的增量 replay 已不可信。此时重置基线为 0，
      // 后续实时事件从 0 重新累计；断线期间丢失的变更由 reconcileAllIncremental 兜底全量对账。
      if (typeof payload.serverSeq === "number" && payload.serverSeq < _lastSeq) {
        _lastSeq = 0;
      }
      // 处理补发的事件
      for (const evt of payload.events) {
        if (evt.event === "resource:changed" && evt.data) {
          const data = evt.data;
          if (data.seq && data.seq > _lastSeq) {
            _lastSeq = data.seq;
          }
          // 触发资源变更处理（与 connect 后的实时事件一致：删除/失效用单数，派发保留原值）
          const singular = SEG_TO_RESOURCE[data.resource] || data.resource;
          if (data.action === "deleted" && data.id != null) {
            void removeFullItemByResource(singular, data.id);
          }
          bumpResourceEvent(singular);
          scheduleResourceReload(data.resource, {
            resource: data.resource,
            id: data.id ?? null,
            action: data.action ?? "changed",
            competitionId: data.competitionId ?? null,
            seq: data.seq ?? null,
            ts: data.ts ?? null,
          });
        }
      }
    },
  );

  // 断线重连成功后：先请求补发遗漏事件，再对账
  onRealtime("connect", () => {
    // 请求补发遗漏事件（使用 socket.ts 的单例引用，避免依赖未定义的 window.__gipfel_socket）。
    // 后端 handleSyncReplay 接收的字段名为 lastSeq，此处保持一致。
    if (_lastSeq > 0) {
      const sock = getSocketInstance();
      if (sock && sock.connected) {
        sock.emit("sync:replay", { lastSeq: _lastSeq });
      }
    }
    // 对账：清理「断线 / 实时事件丢失期间」被删除的条目
    void reconcileAllIncremental();
  });
}
