import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import VueKonva from "vue-konva";
import "element-plus/dist/index.css";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import * as ElementPlusIconsVue from "@element-plus/icons-vue";
import App from "./App.vue";
import router from "./router";
import "./assets/styles/global.scss";
// 注册自定义仪表盘控件（必须在 app.mount 之前执行）
import "./components/dashboard/registerCustomWidgets";
// 账号隔离：在挂载前完成本地存储迁移（旧顶层 token → 账号命名空间；清理遗留共享 DB），
// 确保各 store 初始化读取 token / 比赛选择时已进入正确的账号命名空间。
import { ensureStorageMigration } from "./utils/accountStorage";
import { deleteOldAccountDbs } from "./api/cache";
import { formatTime } from "./utils/format";

ensureStorageMigration();
// 清理升级前「仅按账号、无 realm」的旧 IndexedDB 缓存库（新方案库名带 realm 段）。
deleteOldAccountDbs();

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(ElementPlus, { locale: zhCn });
app.use(VueKonva);

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component);
}

// 全局时间格式化：截断到秒（统一引用 format.ts 的 formatTime，单一真源）
app.config.globalProperties.$formatTime = formatTime;

// 全局错误兜底：捕获渲染/生命周期/侦听器中未被组件级 ErrorBoundary 接住的异常，
// 统一打到控制台，便于定位根因（如「创建数据后空白」类崩溃），避免静默白屏。
app.config.errorHandler = (err, instance, info) => {
  // eslint-disable-next-line no-console
  console.error(
    "[全局错误] 未捕获的渲染/逻辑异常：",
    err,
    "\n组件实例：",
    instance,
    "\n错误位置(info)：",
    info,
  );
};

// 未处理的 Promise 异常（如实时同步/缓存回填中的 reject）同样打到控制台，便于排查。
window.addEventListener("unhandledrejection", (e: PromiseRejectionEvent) => {
  // eslint-disable-next-line no-console
  console.error("[未处理的 Promise 异常]", e.reason);
});

app.mount("#app");
