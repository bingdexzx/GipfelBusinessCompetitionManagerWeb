/**
 * ============================================================
 *  自定义控件注册入口
 * ============================================================
 * 静态控件：在此 import 并 registerCustomWidget。
 * 动态控件包：启动时从 API 拉取列表，用 script 标签加载 component.js。
 * ============================================================
 */
import { registerCustomWidget } from "./types";
import { widgetPackagesApi } from "@/api";

// —— 在此追加你自己的静态控件 ——
// import MyWidget from "./widgets/MyWidget.vue";
// registerCustomWidget({ type: "my-widget", label: "我的控件", component: MyWidget });

/** 通过 script 标签加载外部 JS，返回全局变量值 */
function loadScript(url: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = url;
    script.onload = () => resolve((window as any).__widget_module__);
    script.onerror = () => reject(new Error(`Failed to load ${url}`));
    document.head.appendChild(script);
  });
}

// —— 动态加载已上传的控件包 ——
async function loadWidgetPackages() {
  try {
    const list = await widgetPackagesApi.list();
    if (!Array.isArray(list)) return;
    for (const pkg of list) {
      if (!pkg.isActive) continue;
      const manifest = pkg.manifest || {};
      try {
        // 清理全局变量，准备接收新控件模块
        (window as any).__widget_module__ = undefined;
        // 通过 script 标签加载 component.js
        // component.js 需要将组件赋值给 window.__widget_module__
        await loadScript(pkg.componentUrl);
        const component = (window as any).__widget_module__;
        if (!component) {
          console.warn(`[控件包] ${pkg.widgetType}: component.js 未设置 window.__widget_module__`);
          continue;
        }
        registerCustomWidget({
          type: pkg.widgetType,
          label: pkg.name,
          component,
          bindable: manifest.bindable !== false,
          description: pkg.description || (manifest.description as string) || "",
          defaultSize: (manifest.defaultSize as { w: number; h: number }) || undefined,
          defaultConfig: (manifest.defaultConfig as Record<string, unknown>) || undefined,
        });
      } catch (e) {
        console.warn(`[控件包] 加载失败: ${pkg.widgetType}`, e);
      }
    }
  } catch {
    /* API 失败不影响静态控件 */
  }
}

// 启动时异步加载，不阻塞应用初始化
loadWidgetPackages();
