import { defineStore } from "pinia";
import { ref } from "vue";
import { currentAnnouncement } from "@/data/announcement";
import { announcementsApi, type AnnouncementItem } from "@/api";
import { getAccountItem, setAccountItem } from "@/utils/accountStorage";

/** 已读公告版本的逻辑键名（实际存储会由 accountStorage 加账号前缀，按账号隔离）。 */
const SEEN_KEY = "announcementSeenVersion";

/**
 * 更新公告 store。
 *
 * 数据全部来自后端 API（数据库），内置硬编码仅保留 currentAnnouncement 作为已读锚点。
 * 管理弹窗可对所有公告进行增删改。
 */
export const useAnnouncementStore = defineStore("announcement", () => {
  const current = currentAnnouncement;
  const visible = ref(false);
  const seenVersion = ref<string>(getAccountItem(SEEN_KEY) || "");

  /** 公告列表（全部来自 API，按 date 倒序） */
  const history = ref<AnnouncementItem[]>([]);

  /** 从 API 拉取公告列表 */
  async function fetchFromApi() {
    try {
      const list: AnnouncementItem[] = (await announcementsApi.list()) || [];
      list.sort((a, b) => b.date.localeCompare(a.date));
      history.value = list;
    } catch {
      /* API 失败时保留旧数据 */
    }
  }

  /** 用户点击「确认」：标记当前版本已读并关闭弹窗。 */
  function confirm() {
    seenVersion.value = current.version;
    setAccountItem(SEEN_KEY, current.version);
    visible.value = false;
  }

  /** 系统设置中点击「查看更新公告」：直接打开。 */
  function openFromSettings() {
    visible.value = true;
  }

  /** 系统设置中显式「标记为已读」：记录已读并不再自动弹出。 */
  function markSeen() {
    seenVersion.value = current.version;
    setAccountItem(SEEN_KEY, current.version);
    visible.value = false;
  }

  return { current, history, visible, confirm, openFromSettings, markSeen, fetchFromApi };
});