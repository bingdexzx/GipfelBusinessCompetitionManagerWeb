import { defineStore } from "pinia";
import { ref } from "vue";
import { announcements, currentAnnouncement } from "@/data/announcement";
import { getAccountItem, setAccountItem } from "@/utils/accountStorage";

/** 已读公告版本的逻辑键名（实际存储会由 accountStorage 加账号前缀，按账号隔离）。 */
const SEEN_KEY = "announcementSeenVersion";

/**
 * 更新公告 store。
 *
 * 设计：公告**不自动弹出**，应用启动直接展示主界面；用户可在「系统设置 - 关于」
 * 中手动打开查看当前/历史更新公告（openFromSettings）。confirm / markSeen 仅用于
 * 手动查看流程的已读状态记录。
 */
export const useAnnouncementStore = defineStore("announcement", () => {
  const current = currentAnnouncement;
  const history = announcements;
  const visible = ref(false);
  const seenVersion = ref<string>(getAccountItem(SEEN_KEY) || "");

  /** 用户点击「确认」：标记当前版本已读并关闭弹窗。 */
  function confirm() {
    seenVersion.value = current.version;
    setAccountItem(SEEN_KEY, current.version);
    visible.value = false;
  }

  /** 系统设置中点击「查看更新公告」：直接打开（不自动标记已读，关闭行为由 confirm 决定）。 */
  function openFromSettings() {
    visible.value = true;
  }

  /** 系统设置中显式「标记为已读」：记录已读并不再自动弹出（保留打开查看能力）。 */
  function markSeen() {
    seenVersion.value = current.version;
    setAccountItem(SEEN_KEY, current.version);
    visible.value = false;
  }

  return { current, history, visible, confirm, openFromSettings, markSeen };
});
