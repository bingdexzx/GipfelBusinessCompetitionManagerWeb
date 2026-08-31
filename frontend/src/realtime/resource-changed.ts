import { onRealtime, getLastReceivedSeq, updateLastReceivedSeq } from "./socket";

/** 资源变更事件类型（与后端 apps/realtime/gateway.py 一致）。 */
export interface ResourceChangedEvent {
  resource: string;
  ids: number[];
  action: "created" | "updated" | "deleted" | "bulk";
  competitionId: number | null;
  seq: number;
  ts: number;
}

export interface PermissionsChangedEvent {
  userId: number;
  version: number;
  seq: number;
  ts: number;
}

type ResourceHandler = (e: ResourceChangedEvent) => void;
type PermissionsHandler = (e: PermissionsChangedEvent) => void;

const resourceHandlers = new Map<string, Set<ResourceHandler>>();
const anyResourceHandlers = new Set<ResourceHandler>();

let bound = false;

/** 注册资源变更监听。resource 为 null 时监听全部资源。返回取消注册函数。 */
export function onResourceChanged(resource: string | null, handler: ResourceHandler): () => void {
  if (!bound) bind();
  if (resource === null) {
    anyResourceHandlers.add(handler);
    return () => anyResourceHandlers.delete(handler);
  }
  let set = resourceHandlers.get(resource);
  if (!set) {
    set = new Set();
    resourceHandlers.set(resource, set);
  }
  set.add(handler);
  return () => set!.delete(handler);
}

let permissionsHandler: PermissionsHandler | null = null;
export function onPermissionsChanged(handler: PermissionsHandler): () => void {
  if (!bound) bind();
  permissionsHandler = handler;
  return () => {
    if (permissionsHandler === handler) permissionsHandler = null;
  };
}

function bind() {
  bound = true;
  onRealtime("resource:changed", (payload: ResourceChangedEvent) => {
    if (payload?.seq != null) updateLastReceivedSeq(payload.seq);
    dispatch(payload);
  });
  onRealtime("permissions:changed", (payload: PermissionsChangedEvent) => {
    if (payload?.seq != null) updateLastReceivedSeq(payload.seq);
    permissionsHandler?.(payload);
  });
  onRealtime("auth:required", (payload: { reason: string }) => {
    // 顶号 / 需改密：触发登出
    window.dispatchEvent(new CustomEvent("auth:kicked", { detail: payload }));
  });
  // 连接成功后请求补发遗漏事件
  onRealtime("connect", () => {
    const socket = getSocketInstance();
    if (socket) {
      socket.emit("sync:replay", { lastSeq: getLastReceivedSeq() });
    }
  });
  onRealtime("sync:replay:result", (payload: { events: any[]; serverSeq: number }) => {
    if (payload?.serverSeq != null) updateLastReceivedSeq(payload.serverSeq);
    for (const e of payload?.events || []) {
      if (e?.event === "resource:changed") dispatch(e.data as ResourceChangedEvent);
    }
  });
}

function dispatch(e: ResourceChangedEvent) {
  if (!e) return;
  const set = resourceHandlers.get(e.resource);
  if (set) for (const h of set) h(e);
  for (const h of anyResourceHandlers) h(e);
}

import { getSocketInstance } from "./socket";
