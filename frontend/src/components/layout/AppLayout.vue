<template>
  <div
    class="app-layout"
    :class="{ 'app-layout--drawer': isCompact, 'app-layout--nav-open': mobileNavOpen }"
  >
    <div class="app-accent"></div>
    <Sidebar :drawer="isCompact" :open="mobileNavOpen" />
    <!-- 抽屉模式下的遮罩：点击关闭侧栏；仅在平板/手机且抽屉打开时出现 -->
    <div
      v-show="isCompact && mobileNavOpen"
      class="sidebar-backdrop"
      @click="mobileNavOpen = false"
    ></div>
    <div class="app-main">
      <TopBar :show-menu-toggle="isCompact" @toggle="mobileNavOpen = !mobileNavOpen" />
      <div class="app-content">
        <div class="route-wrap">
          <!-- 页面级错误边界：单个路由页面渲染异常时仅隔离该页面，避免整应用白屏。 -->
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
import { watch } from "vue";
import Sidebar from "./Sidebar.vue";
import TopBar from "./TopBar.vue";
import ErrorBoundary from "@/components/common/ErrorBoundary.vue";
import { useAuthStore } from "@/stores/auth";
import { useConfigStore } from "@/stores/config";
import { useCompetitionStore } from "@/stores/competition";
import { useMessageStore } from "@/stores/message";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { ref } from "vue";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const configStore = useConfigStore();
const compStore = useCompetitionStore();
const messageStore = useMessageStore();
const { isCompact } = useBreakpoint();

// 平板/手机下侧栏为抽屉模式，默认收起；由顶栏汉堡按钮或路由切换控制开关。
const mobileNavOpen = ref(false);
// 切换路由（含点击菜单项）后自动收起抽屉，避免遮挡新页面。
watch(
  () => route.fullPath,
  () => {
    mobileNavOpen.value = false;
  },
);
// 放大回桌面尺寸时强制收起，恢复固定侧栏布局。
watch(isCompact, (compact) => {
  if (!compact) mobileNavOpen.value = false;
});

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

</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh; /* 回退：老浏览器不支持 dvh 时仍可用 */
  height: 100dvh; /* 移动端动态视口高度：避开地址栏导致底部被裁切、内容不可达 */
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
/* 抽屉遮罩：覆盖主区与顶栏，置于抽屉之下、内容之上。仅抽屉模式启用过渡。 */
.sidebar-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  opacity: 0;
  transition: opacity var(--dur-base) var(--ease-out-expo);
}
.app-layout--nav-open .sidebar-backdrop {
  opacity: 1;
}
/* 抽屉模式下，打开时锁定 body 滚动（与抽屉滑入同步） */
.app-layout--drawer.app-layout--nav-open {
  overflow: hidden;
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
  -webkit-overflow-scrolling: touch; /* iOS 惯性滚动 */
  overscroll-behavior: contain; /* 避免连锁触发外层滚动/下拉刷新 */
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
