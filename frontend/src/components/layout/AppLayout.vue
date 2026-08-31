<template>
  <div class="app-layout">
    <div class="app-accent"></div>
    <Sidebar />
    <div class="app-main">
      <TopBar />
      <div class="app-content">
        <div class="route-wrap">
          <!-- 页面级错误边界：单个路由页面渲染异常时仅隔离该页面，
               侧边栏/顶栏与其它界面保持可用，避免整应用白屏（此前「创建一个数据后所有界面空白」的根因）。 -->
          <ErrorBoundary :key="route.fullPath">
            <router-view :key="route.fullPath" />
          </ErrorBoundary>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from "vue-router";
import { onMounted, onBeforeUnmount, watch } from "vue";
import Sidebar from "./Sidebar.vue";
import TopBar from "./TopBar.vue";
import ErrorBoundary from "@/components/common/ErrorBoundary.vue";
import { useAuthStore } from "@/stores/auth";
import { useConfigStore } from "@/stores/config";
import { useCompetitionStore } from "@/stores/competition";
import { useMessageStore } from "@/stores/message";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const configStore = useConfigStore();
const compStore = useCompetitionStore();
const messageStore = useMessageStore();

// 拉取账号资料后：归属比赛的账号（competitionId 非空）自动锁定并显示所属比赛，
// 无需手动选择，也避免 localStorage 残留其他比赛导致请求越权（403）。
// 超管 / 未分配账号（competitionId 为空）保持原手动选择逻辑。
authStore.fetchProfile().then(() => {
  compStore.applyOwnCompetition(authStore.user?.competitionId ?? null);
  // 初始化消息中心实时监听并拉取未读红点（仅 message:view 权限账号生效，其余静默）。
  messageStore.initRealtime();
  messageStore.fetchUnread();
});
configStore.loadConfig();

// 强制改密：拉取资料后发现仍需改密，跳回登录页触发改密对话框
watch(
  () => authStore.needsPasswordChange,
  (need) => {
    if (need) router.push("/login");
  },
  { immediate: true },
);

// 跟踪任意弹窗(overlay)开关，给 body 加 modal-open，用于整片背景（含标题栏）统一虚化。
// 打开：遮罩节点一插入 DOM（哪怕 opacity 还是 0、正要淡入）就同步加模糊，与窗口同帧起步，不滞后。
// 关闭：捕获遮罩 opacity 从 1→0 的离场过渡【开始】瞬间，立即移除模糊，
//       于是点 ×/取消/确定/点空白处——窗口刚开始退出的那一刻，背景就变清晰，
//       模糊不再跟着退场动画“滞后消失”。
// closingOverlays 记录“正在关闭”的遮罩：离场中途其 class 还会变动，必须跳过它，
// 否则会被重新判定为“可见”而把模糊又加回来。
let overlayObserver: MutationObserver | null = null;
const closingOverlays = new Set<Element>();

function isOverlayVisible(el: Element): boolean {
  if (closingOverlays.has(el)) return false; // 正在关闭的遮罩不算“打开中”
  if (el.getClientRects().length === 0) return false;
  const cs = getComputedStyle(el as HTMLElement);
  if (cs.display === "none") return false;
  return true;
}
function syncModalState() {
  // 清理已脱离文档的残留引用
  for (const el of closingOverlays) {
    if (!el.isConnected) closingOverlays.delete(el);
  }
  const visible = [...document.querySelectorAll(".el-overlay")].some(isOverlayVisible);
  document.body.classList.toggle("modal-open", visible);
}
// 离场过渡开始：遮罩从 1→0 淡出，此刻计算 opacity 仍为起始值 1。
// 立即把该遮罩标记为关闭并去掉 modal-open，让模糊在窗口退出那一刻同步消失。
function onOverlayTransitionStart(e: TransitionEvent) {
  const el = e.target as HTMLElement | null;
  if (!el || !el.classList?.contains("el-overlay")) return;
  if (e.propertyName !== "opacity") return;
  const op = parseFloat(getComputedStyle(el).opacity);
  if (op > 0.5 && !closingOverlays.has(el)) {
    closingOverlays.add(el);
    syncModalState(); // 立刻移除 modal-open（模糊瞬间消失）
  }
}
function onOverlayTransitionEnd(e: TransitionEvent) {
  const el = e.target as HTMLElement | null;
  if (!el || !el.classList?.contains("el-overlay")) return;
  if (e.propertyName !== "opacity") return;
  // 离场结束：解除关闭标记，重新校准一次（兜底）
  closingOverlays.delete(el);
  syncModalState();
}
onMounted(() => {
  overlayObserver = new MutationObserver(syncModalState);
  overlayObserver.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
  });
  document.addEventListener("transitionstart", onOverlayTransitionStart, true);
  document.addEventListener("transitionend", onOverlayTransitionEnd, true);
  syncModalState();
});
onBeforeUnmount(() => {
  overlayObserver?.disconnect();
  document.removeEventListener("transitionstart", onOverlayTransitionStart, true);
  document.removeEventListener("transitionend", onOverlayTransitionEnd, true);
  document.body.classList.remove("modal-open");
});
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  position: relative;
}
.app-accent {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--gradient-brand);
  z-index: 100;
}
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-bg);
  position: relative;
}
.app-main::before {
  content: "";
  position: absolute;
  top: -160px;
  right: -120px;
  width: 420px;
  height: 420px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.08), rgba(6, 182, 212, 0) 70%);
  pointer-events: none;
  z-index: 0;
  animation: glow-drift 20s ease-in-out infinite alternate;
}
.app-main::after {
  content: "";
  position: absolute;
  bottom: -180px;
  left: 200px;
  width: 380px;
  height: 380px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.06), rgba(139, 92, 246, 0) 70%);
  pointer-events: none;
  z-index: 0;
  animation: glow-drift 25s ease-in-out infinite alternate-reverse;
}
@keyframes glow-drift {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(30px, 20px) scale(1.1); }
}
.app-content {
  position: relative;
  z-index: 1;
  flex: 1;
  overflow: auto;
  padding: var(--content-padding);
}
.route-wrap {
  width: 100%;
  min-height: 100%;
  /* 改为 flex 列容器：让直接子页面（如仪表盘）可用 flex:1 真正撑满，
     不再依赖脆弱的百分比高度（父级无确定 height 时 height:100% 会解析失败、塌缩）。 */
  display: flex;
  flex-direction: column;
}
</style>
