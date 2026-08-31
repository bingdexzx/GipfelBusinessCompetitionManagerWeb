import { watch } from "vue";
import { useCompetitionStore } from "@/stores/competition";

/**
 * 统一处理「切换比赛 → 先清空旧数据再重新拉取」，消除切换比赛时停留在
 * 上一个比赛旧数据的「错误内容跳变」问题（意图⑰ 的统一化延伸）。
 *
 * 与各个视图自身的 loading 闸门（el-table v-loading / 首屏空白）配合：
 * 切比赛时同步清空数据引用，网络确认后才回填，加载间隙显示加载态而非旧行。
 *
 * 注意：仅当比赛 id 实际变化（且非空）时才清空旧数据；reload() 始终调用，
 * 由被调函数自身用 `if (!compStore.competitionId)` 守卫来安全处理「未选比赛」。
 *
 * @param reload 重新拉取数据的函数（通常与 onMounted 中调用的同一序列一致）
 * @param clear  切比赛时先同步清空的数据引用（避免旧行在加载间隙闪现）
 */
export function useCompetitionReload(reload: () => void, clear?: () => void) {
  const compStore = useCompetitionStore();
  watch(
    () => compStore.competitionId,
    (newId, oldId) => {
      if (newId && newId !== oldId) {
        clear?.();
      }
      reload();
    },
  );
}
