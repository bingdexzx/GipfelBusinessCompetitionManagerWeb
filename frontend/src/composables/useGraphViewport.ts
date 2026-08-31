/**
 * 节点图可视化编辑器的「画布缩放 / 平移」能力（合同类型、产业字段共用）。
 *
 * 设计要点：
 * - 世界坐标（节点 node.x/node.y、连线 svgW/svgH）完全不变，所有缩放/平移只作用于
 *   一个包裹层 `.ge-viewport` 的 CSS transform: translate(panX, panY) scale(zoom)。
 *   这样连线、节点、端口的相对位置天然保持一致，端口点击/连线/删除也不受影响
 *   （浏览器命中测试会自动考虑 transform）。
 * - 平移(pan) 用屏幕像素增量（panX/panY 本身是屏幕空间偏移），直接累加鼠标位移。
 * - 缩放(zoom) 以鼠标位置为锚点：保持该屏幕点下的「世界坐标」在缩放前后不动，
 *   公式为 pan' = mouse - (mouse - pan) / zoom * zoom'。
 * - 节点拖拽时，屏幕位移需除以 zoom 才能换算回世界坐标（调用方在 onDragMove 里处理）。
 */
import { ref, computed } from "vue";

export function useGraphViewport() {
  const zoom = ref(1);
  const panX = ref(0);
  const panY = ref(0);
  /** 视口（裁剪框）元素：滚轮以鼠标为中心 / 适应视图时取其实际像素尺寸 */
  const canvasRef = ref<HTMLElement | null>(null);

  const MIN_ZOOM = 0.3;
  const MAX_ZOOM = 2.5;

  const viewportStyle = computed(() => ({
    transform: `translate(${panX.value}px, ${panY.value}px) scale(${zoom.value})`,
    transformOrigin: "0 0",
  }));

  function clampZoom(z: number): number {
    return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z));
  }

  /** 以鼠标为中心缩放：保持鼠标点下的世界坐标不动 */
  function zoomAt(next: number, clientX?: number, clientY?: number): void {
    const nz = clampZoom(next);
    if (nz === zoom.value) return;
    const rect = canvasRef.value?.getBoundingClientRect();
    if (rect && clientX != null && clientY != null) {
      const mx = clientX - rect.left;
      const my = clientY - rect.top;
      panX.value = mx - ((mx - panX.value) / zoom.value) * nz;
      panY.value = my - ((my - panY.value) / zoom.value) * nz;
    }
    zoom.value = nz;
  }

  function zoomIn(): void {
    zoomAt(zoom.value * 1.2);
  }
  function zoomOut(): void {
    zoomAt(zoom.value / 1.2);
  }

  /** 适应：把世界内容(contentW × contentH，通常用 svgW/svgH) 缩放进视口并居中 */
  function fitView(contentW: number, contentH: number): void {
    const rect = canvasRef.value?.getBoundingClientRect();
    if (!rect || contentW <= 0 || contentH <= 0) return;
    const z = clampZoom(Math.min(rect.width / contentW, rect.height / contentH) * 0.92);
    zoom.value = z;
    panX.value = (rect.width - contentW * z) / 2;
    panY.value = (rect.height - contentH * z) / 2;
  }

  function resetView(): void {
    zoom.value = 1;
    panX.value = 0;
    panY.value = 0;
  }

  /** 滚轮缩放（模板用 @wheel.prevent 绑定，避免页面滚动） */
  function onWheel(e: WheelEvent): void {
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    zoomAt(zoom.value * factor, e.clientX, e.clientY);
  }

  /** 在画布空白处按下并拖动 = 平移整个视图 */
  function startPan(e: MouseEvent): void {
    const sx = e.clientX;
    const sy = e.clientY;
    const ox = panX.value;
    const oy = panY.value;
    function move(ev: MouseEvent) {
      panX.value = ox + (ev.clientX - sx);
      panY.value = oy + (ev.clientY - sy);
    }
    function up() {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  }

  return {
    zoom,
    panX,
    panY,
    canvasRef,
    viewportStyle,
    zoomIn,
    zoomOut,
    fitView,
    resetView,
    onWheel,
    startPan,
    MIN_ZOOM,
    MAX_ZOOM,
  };
}
