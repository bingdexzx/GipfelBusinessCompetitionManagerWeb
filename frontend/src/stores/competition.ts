import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { competitionsApi } from "@/api";
import {
  connectRealtime,
  disconnectRealtime,
  subscribeCompetition,
  unsubscribeCompetition,
  onRealtime,
} from "@/realtime/socket";
import { onResourceChanged } from "@/realtime/resource-changed";
import { getAccountItem, setAccountItem, removeAccountItem } from "@/utils/accountStorage";

export interface Competition {
  id: number;
  name: string;
  status: string;
  mapBackground?: string | null;
  stockConfig?: unknown;
  fiscalYears?: { id: number; year: number; status: string }[];
  createdAt?: string;
  updatedAt?: string;
}

type CompetitionSelection = Partial<Competition> & { id: number };

export const useCompetitionStore = defineStore("competition", () => {
  const list = ref<Competition[]>([]);
  const selected = ref<CompetitionSelection | null>(null);
  const fiscalYears = ref<any[]>([]);
  const currentFiscalYear = ref<number | null>(null);
  const fiscalYearLoading = ref(false);

  // 简化 API（已存在视图使用）
  const currentId = computed(() => selected.value?.id ?? null);
  const current = computed(() => selected.value);
  const competitionId = currentId;
  const competitionName = computed(() => selected.value?.name || "");

  async function load() {
    const res: any = await competitionsApi.list();
    list.value = Array.isArray(res) ? res : res?.items ?? [];
    // 恢复上次选择
    const saved = localStorage.getItem("gipfel:currentCompetitionId");
    if (saved !== null) {
      const id = Number(saved);
      if (list.value.some((c) => c.id === id)) await select(id);
    }
    if (selected.value === null && list.value.length) await select(list.value[0].id);
  }

  async function select(id: number | null) {
    if (id === null) {
      clearSelection();
      return;
    }
    const comp = list.value.find((c) => c.id === id) || { id };
    selectCompetition(comp);
  }

  /** 选择比赛：锁定、订阅实时房间、拉取财年 */
  function selectCompetition(comp: CompetitionSelection) {
    if (selected.value?.id) unsubscribeCompetition(selected.value.id);
    selected.value = comp;
    localStorage.setItem("gipfel:currentCompetitionId", String(comp.id));
    setAccountItem("currentCompetition", JSON.stringify(comp));
    currentFiscalYear.value = null;
    fiscalYearLoading.value = true;
    loadFiscalYear(comp.id);
    connectRealtime();
    subscribeCompetition(comp.id);
    bindRealtime();
  }

  function clearSelection() {
    if (selected.value) unsubscribeCompetition(selected.value.id);
    disconnectRealtime();
    selected.value = null;
    fiscalYears.value = [];
    currentFiscalYear.value = null;
    fiscalYearLoading.value = false;
    localStorage.removeItem("gipfel:currentCompetitionId");
    removeAccountItem("currentCompetition");
  }

  /** 归属比赛账号自动锁定 */
  async function applyOwnCompetition(ownId: number | null | undefined) {
    if (ownId == null) return;
    if (selected.value?.id === ownId) return;
    try {
      const comp: any = await competitionsApi.get(ownId);
      if (comp && comp.id != null) selectCompetition(comp);
    } catch {
      clearSelection();
    }
  }

  async function loadFiscalYear(compId: number) {
    fiscalYearLoading.value = true;
    try {
      const res: any = await competitionsApi.fiscalYears.list(compId);
      const arr = Array.isArray(res) ? res : res?.items ?? [];
      fiscalYears.value = arr;
      const active = arr.find((f: any) => f.status === "ACTIVE");
      currentFiscalYear.value = active ? active.year : null;
    } catch {
      currentFiscalYear.value = null;
      fiscalYears.value = [];
    } finally {
      fiscalYearLoading.value = false;
    }
  }

  function reconnectRealtime() {
    disconnectRealtime();
    connectRealtime();
    if (selected.value?.id) {
      subscribeCompetition(selected.value.id);
      loadFiscalYear(selected.value.id);
    }
    bindRealtime();
  }

  // ===== 实时广播处理 =====
  function handleFiscalYearChanged(payload: any) {
    if (!payload?.competitionId || payload.competitionId !== currentId.value) return;
    const fy = payload.fiscalYear;
    if (!fy) {
      loadFiscalYear(payload.competitionId);
      return;
    }
    if (fy.status === "ACTIVE") currentFiscalYear.value = fy.year;
    else if (fy.status === "CLOSED" && currentFiscalYear.value === fy.year)
      currentFiscalYear.value = null;
    loadFiscalYear(payload.competitionId);
  }
  let bound = false;
  function bindRealtime() {
    if (bound) return;
    bound = true;
    onRealtime("fiscal-year:changed", handleFiscalYearChanged);
  }

  // 从本地存储恢复选择
  try {
    const token = getAccountItem("token");
    if (token) {
      const raw = getAccountItem("currentCompetition");
      if (raw) {
        const comp = JSON.parse(raw);
        if (comp && comp.id != null) {
          selected.value = comp;
          connectRealtime();
          subscribeCompetition(comp.id);
          bindRealtime();
          loadFiscalYear(comp.id);
        }
      }
    }
  } catch {
    /* ignore */
  }

  // 资源变更：比赛本身被改动时刷新列表
  onResourceChanged("competitions", () => {
    void load();
  });

  return {
    // 简化 API
    list,
    currentId,
    current,
    load,
    select,
    // 原 API 别名
    selected,
    fiscalYears,
    currentFiscalYear,
    fiscalYearLoading,
    competitionId,
    competitionName,
    selectCompetition,
    clearSelection,
    applyOwnCompetition,
    loadFiscalYear,
    reconnectRealtime,
  };
});
