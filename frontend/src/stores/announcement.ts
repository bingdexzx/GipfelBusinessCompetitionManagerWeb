import { defineStore } from "pinia";
import { ref } from "vue";
import { announcements as builtinAnnouncements, currentAnnouncement } from "@/data/announcement";
import { announcementsApi, type AnnouncementItem } from "@/api";
import { getAccountItem, setAccountItem } from "@/utils/accountStorage";

/** 已读公告版本的逻辑键名（实际存储会由 accountStorage 加账号前缀，按账号隔离）。 */
const SEEN_KEY = "announcementSeenVersion";

export interface DisplayAnnouncement {
  version: string;
  title: string;
  date: string;
  content: string;
  /** 来源：builtin=硬编码，api=在线管理 */
  source: "builtin" | "api";
}

/**
 * 更新公告 store。
 *
 * 数据来源合并：
 *  - 内置公告（硬编码在 data/announcement.ts，作为兜底）
 *  - 在线公告（通过 API 获取，仅 isActive=true 的会展示）
 *
 * 弹窗已读逻辑不变：以 currentAnnouncement.version 为锚点。
 */
export const useAnnouncementStore = defineStore("announcement", () => {
  const current = currentAnnouncement;
  const visible = ref(false);
  const seenVersion = ref<string>(getAccountItem(SEEN_KEY) || "");

  /** 合并后的公告列表（API 优先，内置兜底，按 date 倒序） */
  const history = ref<DisplayAnnouncement[]>(
    builtinAnnouncements.map((a) => ({
      version: a.version,
      title: a.title,
      date: a.date,
      content: a.content,
      source: "builtin" as const,
    })),
  );

  /** 从 API 拉取在线公告并合并 */
  async function fetchFromApi() {
    try {
      const apiList: AnnouncementItem[] = (await announcementsApi.list()) || [];
      const apiItems: DisplayAnnouncement[] = apiList
        .filter((a) => a.isActive)
        .map((a) => ({
          version: a.version,
          title: a.title,
          date: a.date,
          content: a.content,
          source: "api" as const,
        }));
      // 合并：API 公告在前，内置公告去重（按 version）
      const seen = new Set(apiItems.map((a) => a.version));
      const merged = [
        ...apiItems,
        ...builtinAnnouncements
          .filter((a) => !seen.has(a.version))
          .map((a) => ({
            version: a.version,
            title: a.title,
            date: a.date,
            content: a.content,
            source: "builtin" as const,
          })),
      ];
      // 按 date 倒序
      merged.sort((a, b) => b.date.localeCompare(a.date));
      history.value = merged;
    } catch {
      /* API 失败时保留内置公告 */
    }
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

  return { current, history, visible, confirm, openFromSettings, markSeen, fetchFromApi };
});