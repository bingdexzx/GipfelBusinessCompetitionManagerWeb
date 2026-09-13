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
import { onRealtime } from "@/realtime/socket";

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
let _loading: Promise<void> | null = null;

/**
 * 拉取并注册所有已上传的控件包。
 *
 * 必须可重入地「重试」：应用启动时（main.ts 引入本模块）通常还没有 token，/widget-packages
 * 会 401，改前只尝试这一次且把异常吞掉 —— 整个会话的自定义控件都不会注册（审计 M-01）。
 * 故登录成功后会再次调用（见文件末尾的 auth:login 监听）；并发调用共用同一个 promise。
 */
export function reloadWidgetPackages(): Promise<void> {
  if (_loading) return _loading;
  _loading = loadWidgetPackages().finally(() => {
    _loading = null;
  });
  return _loading;
}

async function loadWidgetPackages(): Promise<void> {
  let list: unknown;
  try {
    list = await widgetPackagesApi.list();
  } catch {
    /* API 失败不影响静态控件（未登录时的 401 走这里，登录后会重试） */
    return;
  }
  if (!Array.isArray(list)) return;
  let registered = 0;
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
        description: pkg.description || (manifest.description as string) || "",
        defaultSize: (manifest.defaultSize as { w: number; h: number }) || undefined,
        defaultConfig: (manifest.defaultConfig as Record<string, unknown>) || undefined,
        fieldSlots: Array.isArray(manifest.fields)
          ? manifest.fields.map((f: any) => ({ key: f.key, label: f.label || f.key, required: !!f.required }))
          : undefined,
        configFields: Array.isArray(manifest.configFields)
          ? manifest.configFields.map((f: any) => ({
              key: f.key,
              label: f.label || f.key,
              type: f.type || "string",
              default: f.default,
              placeholder: f.placeholder,
              min: f.min,
              max: f.max,
              options: f.options,
            }))
          : undefined,
      });
      registered += 1;
    } catch (e) {
      console.warn(`[控件包] 加载失败: ${pkg.widgetType}`, e);
    }
  }
  // 有控件新注册完成：通知已挂载的仪表盘重新读取本地布局。
  // 它此前可能已经把「类型未注册」的控件当成不可渲染项跳过（条目仍保留在存储里，
  // 见 layoutStorage.ts），这里让它无需刷新页面就能显示出来（审计 M-01）。
  if (registered > 0 && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("widget-registry:changed"));
  }
}

// 启动时异步加载，不阻塞应用初始化
void reloadWidgetPackages();

// 登录成功后再来一次：启动时无 token 的那次必然 401，不重试则本会话看不到任何自定义控件。
window.addEventListener("auth:login", () => {
  void reloadWidgetPackages();
});

// 监听控件包变更广播（超管上传/启停/删除时后端推送），所有在线用户自动刷新
onRealtime("widget-package:changed", () => {
  window.location.reload();
});
