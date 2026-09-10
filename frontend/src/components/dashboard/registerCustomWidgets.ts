/**
 * ============================================================
 *  自定义控件注册入口
 * ============================================================
 * 在这里把你写好的控件组件 import 进来，并调用 registerCustomWidget(...)
 * 完成注册。注册成功后，该控件会自动出现在仪表盘「添加控件」菜单中，
 * 并复用现有的拖拽 / 缩放 / 编辑外壳。
 *
 * 本文件已在 main.ts 中被 import，会在应用启动前完成所有静态注册。
 * 此外，还会自动从后端 API 加载已上传的控件包（动态注册）。
 * ============================================================
 */
import { defineAsyncComponent } from "vue";
import { registerCustomWidget } from "./types";
import { widgetPackagesApi } from "@/api";

// —— 在此追加你自己的静态控件 ——
// import MyWidget from "./widgets/MyWidget.vue";
// registerCustomWidget({ type: "my-widget", label: "我的控件", component: MyWidget });

// —— 动态加载已上传的控件包 ——
async function loadWidgetPackages() {
  try {
    const list = await widgetPackagesApi.list();
    if (!Array.isArray(list)) return;
    for (const pkg of list) {
      if (!pkg.isActive) continue;
      const manifest = pkg.manifest || {};
      try {
        // 动态导入控件包的 component.js
        // Vite 的 dynamic import 需要完整的 URL 路径
        const mod = await import(/* @vite-ignore */ pkg.componentUrl);
        const component = mod.default || mod;
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
