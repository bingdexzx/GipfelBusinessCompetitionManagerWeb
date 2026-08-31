import { defineStore } from "pinia";
import { ref } from "vue";
import { messagesApi } from "@/api";
import { connectRealtime, onRealtime } from "@/realtime/socket";

/** 一条滑入弹窗消息（实时推送触发）。 */
export interface ToastMessage {
  /** 本地唯一键（用于 transition-group 的 DOM 跟踪与定时移除） */
  key?: string;
  /** 消息 id */
  id: number;
  title: string;
  content: string;
  senderName?: string;
  images?: { url: string; filename: string }[];
  createdAt: string;
}

/**
 * 消息中心 store。
 *
 * 职责：
 *  - 维护未读红点计数（unreadCount），供侧边栏徽标与消息中心页使用；
 *  - 维护实时滑入弹窗队列（toasts）：收到 `message:new` 后从右侧滑入，停留约 6s 后自动向右滑出关闭；
 *  - 在登录后（AppLayout 拉取资料）初始化一次实时监听；离线用户登录后通过收件箱看到未读。
 */
export const useMessageStore = defineStore("message", () => {
  const unreadCount = ref(0);
  const toasts = ref<ToastMessage[]>([]);

  let initialized = false;
  let toastSeq = 0;
  const AUTO_CLOSE_MS = 6000;

  /** 拉取未读计数（收件箱维度）。无权限 / 未登录静默失败。 */
  async function fetchUnread() {
    try {
      const res: any = await messagesApi.unreadCount();
      unreadCount.value = res?.count ?? 0;
    } catch {
      // 未登录或缺少 message:view 时忽略
    }
  }

  /** 兼容 MessageToastHost 旧名 */
  function setUnread(n: number) {
    unreadCount.value = Math.max(0, n);
  }

  /** 从队列移除一条弹窗（MessageToastHost 用 id 调用）。 */
  function dismissToast(id: number) {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  }

  /** 兼容原 store 命名：按 key 移除 */
  function removeToast(key: string) {
    const idx = toasts.value.findIndex((t) => t.key === key);
    if (idx !== -1) toasts.value.splice(idx, 1);
  }

  /** 入队一条滑入弹窗；约 6s 后自动向右滑出关闭。 */
  function pushToast(item: ToastMessage) {
    const key = item.key ?? `t${++toastSeq}`;
    toasts.value.push({ key, ...item });
    window.setTimeout(() => removeToast(key), AUTO_CLOSE_MS);
  }

  /** 实时收到新消息：入队弹窗 + 刷新未读红点。 */
  function onNewMessage(payload: any) {
    if (!payload || typeof payload.id !== "number") return;
    pushToast({
      id: payload.id,
      title: payload.title ?? "新消息",
      content: payload.content ?? "",
      senderName: payload.senderName ?? "",
      images: payload.images ?? [],
      createdAt: payload.createdAt ?? new Date().toISOString(),
    });
    fetchUnread();
  }

  /** 初始化实时监听（幂等，仅在登录后调用一次）。 */
  function initRealtime() {
    if (initialized) return;
    initialized = true;
    // 先确保 socket 已建立（此时 token 已存在），再注册事件监听，
    // 规避 socket.ts 中「无 token 时 socket 为 null、on 被跳过」的懒加载陷阱。
    connectRealtime();
    onRealtime("message:new", onNewMessage);
    // 兼容旧事件名（部分后端可能仍用 message:received）
    onRealtime("message:received", onNewMessage);
  }

  /** 重置实时监听幂等锁：socket 因改服务器地址 / 被顶号重建后，旧 handler 绑在旧实例上失效，
   *  需在下次连接成功时重新绑定，否则新消息实时推送会静默丢失。 */
  function resetRealtime() {
    initialized = false;
    initRealtime();
  }
  if (typeof window !== "undefined") {
    window.addEventListener("server:changed", resetRealtime);
    window.addEventListener("auth:kicked", resetRealtime);
  }

  /** 全部标记为已读（消息中心页调用），成功后清零红点。 */
  async function markAllRead() {
    try {
      await messagesApi.markAllRead();
      unreadCount.value = 0;
    } catch {
      // 忽略
    }
  }

  return {
    unreadCount,
    toasts,
    fetchUnread,
    setUnread,
    pushToast,
    dismissToast,
    removeToast,
    initRealtime,
    resetRealtime,
    markAllRead,
  };
});
