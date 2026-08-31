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
import { formatTime } from "./utils/format";

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(ElementPlus, { locale: zhCn });
app.use(VueKonva);

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component as any);
}

app.config.globalProperties.$formatTime = formatTime;

// 全局错误兜底：捕获渲染/生命周期中未捕获异常，避免静默白屏
app.config.errorHandler = (err, instance, info) => {
  // eslint-disable-next-line no-console
  console.error("[全局错误] 未捕获的渲染/逻辑异常：", err, "\n组件实例：", instance, "\n错误位置(info)：", info);
};

if (typeof window !== "undefined") {
  window.addEventListener("unhandledrejection", (e: PromiseRejectionEvent) => {
    // eslint-disable-next-line no-console
    console.error("[未处理的 Promise 异常]", e.reason);
  });
}

app.mount("#app");
