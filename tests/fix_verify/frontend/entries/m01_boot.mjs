/**
 * M-01 验证入口的「真实模块接线」：必须在 registerCustomWidgets 之前 import，
 * 因为该模块在**导入时**就会发起一次 /widget-packages 请求（改前是唯一一次）。
 *
 * 这里把 axios adapter 换成计数器：
 *   - 无 token（启动阶段）→ 按真实后端行为返回 401；
 *   - 有 token → 返回一个启用中的控件包，并要求 document 桩「执行」它的 component.js。
 */
import api from "@/api";
import { getAccountItem } from "@/utils/accountStorage";

export const state = {
  /** GET /widget-packages 的请求次数（每次调用必打网络：该接口 cache:false） */
  listCalls: 0,
  loginCalls: 0,
  requests: [],
};

export const PACKAGE = {
  id: 1,
  name: "演示控件",
  widgetType: "demo-gauge",
  componentUrl: "/media/widget-packages/demo/component.js",
  isActive: true,
  manifest: {
    description: "验证用控件",
    defaultSize: { w: 200, h: 100 },
    fields: [{ key: "value", label: "数值", required: true }],
    configFields: [{ key: "color", label: "颜色", type: "color" }],
  },
};

function ok(config, data) {
  return {
    data: { code: 0, message: "ok", data },
    status: 200,
    statusText: "OK",
    headers: {},
    config,
  };
}

function unauthorized(config) {
  return {
    config,
    message: "Request failed with status code 401",
    response: { status: 401, statusText: "Unauthorized", data: { message: "Unauthorized" }, headers: {}, config },
  };
}

api.defaults.adapter = (config) => {
  const url = String(config.url || "");
  state.requests.push(url);

  if (url.includes("/auth/login")) {
    state.loginCalls += 1;
    return Promise.resolve(
      ok(config, {
        token: "token-u1",
        user: {
          id: 1,
          username: "u1",
          role: "COMPETITION_ADMIN",
          permissions: [],
          companyScopes: [],
        },
      }),
    );
  }

  if (url.includes("/widget-packages")) {
    state.listCalls += 1;
    // 未登录：后端返回 401（拦截器在本地无登录态时静默丢弃，不产生副作用）
    if (!getAccountItem("token")) return Promise.reject(unauthorized(config));
    return Promise.resolve(ok(config, [PACKAGE]));
  }

  return Promise.resolve(ok(config, null));
};

export { api };
