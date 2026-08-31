import { ref, computed, onMounted, onUnmounted } from "vue";

/**
 * 响应式断点 composable（纯展示层，不改任何业务/视觉风格）。
 *
 * 断点约定（与 variables.scss 的 @media 保持一致）：
 *   - isTablet  ≤ 1024px：平板及更窄 —— 侧栏进入「抽屉模式」
 *   - isMobile  ≤ 640px ：手机 —— 进一步收紧密度、隐藏面包屑等
 *
 * 基于 window.matchMedia，监听变化即时更新；组件卸载自动清理监听。
 */
export function useBreakpoint() {
  const isMobile = ref(false);
  const isTablet = ref(false);

  let mqMobile: MediaQueryList | null = null;
  let mqTablet: MediaQueryList | null = null;

  function apply() {
    if (mqMobile) isMobile.value = mqMobile.matches;
    if (mqTablet) isTablet.value = mqTablet.matches;
  }

  function onMobileChange() {
    isMobile.value = mqMobile?.matches ?? false;
  }
  function onTabletChange() {
    isTablet.value = mqTablet?.matches ?? false;
  }

  onMounted(() => {
    // 旧浏览器（无 addEventListener 的 MediaQueryList）降级为 resize 轮询
    mqMobile = window.matchMedia("(max-width: 640px)");
    mqTablet = window.matchMedia("(max-width: 1024px)");
    apply();
    if (mqMobile.addEventListener) {
      mqMobile.addEventListener("change", onMobileChange);
      mqTablet?.addEventListener("change", onTabletChange);
    } else {
      const onResize = () => apply();
      window.addEventListener("resize", onResize);
      onUnmounted(() => window.removeEventListener("resize", onResize));
    }
  });

  onUnmounted(() => {
    if (mqMobile?.removeEventListener) {
      mqMobile.removeEventListener("change", onMobileChange);
      mqTablet?.removeEventListener("change", onTabletChange);
    }
  });

  /** ≤ 1024px：平板及手机 —— 侧栏抽屉模式 */
  const isCompact = computed(() => isTablet.value);
  /** ≤ 640px：手机 */
  const isPhone = computed(() => isMobile.value);

  return { isMobile, isTablet, isCompact, isPhone };
}
