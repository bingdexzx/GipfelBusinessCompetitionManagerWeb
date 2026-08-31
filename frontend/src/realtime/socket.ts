import { io, type Socket } from "socket.io-client";
import { getApiBaseUrl, versionBlocked } from "@/config";
import { getAccountItem } from "@/utils/accountStorage";
import { logger } from "@/utils/logger";

let socket: Socket | null = null;
let connectedBaseUrl: string | null = null;
let reconnectHandler: (() => void) | null = null;
let lastReceivedSeq = 0;

function getBaseUrl(): string {
  return getApiBaseUrl();
}

function getToken(): string | null {
  return getAccountItem("token");
}

/** 建立/复用实时连接（无 token 不连接）。版本封锁期间禁止建连。 */
export function connectRealtime(): Socket | null {
  if (versionBlocked.value) {
    disconnectRealtime();
    return null;
  }
  if (socket) {
    if (connectedBaseUrl && connectedBaseUrl !== getBaseUrl()) {
      socket.disconnect();
      socket = null;
    } else {
      return socket;
    }
  }
  const token = getToken();
  if (!token) return null;
  connectedBaseUrl = getBaseUrl();
  socket = io(connectedBaseUrl || window.location.origin, {
    auth: { token },
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 2000,
  });
  socket.on("connect_error", (err: Error) => {
    logger.error("[Realtime] 连接失败:", err.message);
  });
  socket.io.on("reconnect", () => {
    reconnectHandler?.();
  });
  return socket;
}

export function disconnectRealtime() {
  if (socket) {
    socket.disconnect();
    socket = null;
  }
}

export function subscribeCompetition(competitionId: number) {
  if (!socket) connectRealtime();
  socket?.emit("subscribe", { competitionId });
}

export function unsubscribeCompetition(competitionId: number) {
  socket?.emit("unsubscribe", { competitionId });
}

export function getSocketInstance(): Socket | null {
  return socket;
}

export function onRealtime(event: string, handler: (payload: any) => void) {
  if (!socket) connectRealtime();
  socket?.on(event, handler);
}

export function offRealtime(event: string, handler?: (payload: any) => void) {
  socket?.off(event, handler as any);
}

export function onReconnect(handler: () => void) {
  reconnectHandler = handler;
}

export function updateLastReceivedSeq(seq: number) {
  if (seq > lastReceivedSeq) lastReceivedSeq = seq;
}

export function getLastReceivedSeq(): number {
  return lastReceivedSeq;
}
