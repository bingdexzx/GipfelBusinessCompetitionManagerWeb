import { defineStore } from "pinia";
import { ref } from "vue";
import { announcements, currentAnnouncement } from "@/data/announcement";
import { getAccountItem, setAccountItem } from "@/utils/accountStorage";

/** 已读公告版本的逻辑键名（实际存储会由 accountStorage 加账号前缀，按账号隔离）。 */
const SEEN_KEY = "announcementSeenVersion";

/**
 * 更新公告 store。
 *
 * 职责：
 *  - 在应用启动（App.vue onMounted）时判定是否应弹出公告；
 *  - 首次打开（本地无已读记录）时**不**自动弹窗，直接展示界面，仅静默将当前版本记为已读，
 *    避免一进系统就被公告遮挡；
 *  - 仅当服务端发布更高版本（已读版本低于当前版本）时才弹出更新公告；
 *  - 用户「确认」后记录已读版本，下次启动不再弹出；
 *  - 系统设置页可重新打开查看当前公告（openFromSettings）。
 */
export const useAnnouncementStore = defineStore("announcement", () => {
  const current = currentAnnouncement;
  const history = announcements;
  const visible = ref(false);
  const seenVersion = ref<string>(getAccountItem(SEEN_KEY) || "");

  /** 应用启动时调用：
   *   - 首次打开（seenVersion 为空）：静默记为已读当前版本，不弹窗，直接展示界面；
   *   - 已读版本 < 当前版本（服务端升级出新公告）：弹出更新公告；
   *   - 已是最新：不弹。 */
  function maybeOpen() {
    if (!seenVersion.value) {
      // 首次打开：默认视为已读当前版本，避免一进界面就弹公告遮挡主界面
      seenVersion.value = current.version;
      setAccountItem(SEEN_KEY, current.version);
      visible.value = false;
      return;
    }
    visible.value = seenVersion.value !== current.version;
  }

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

  return { current, history, visible, maybeOpen, confirm, openFromSettings, markSeen };
});
