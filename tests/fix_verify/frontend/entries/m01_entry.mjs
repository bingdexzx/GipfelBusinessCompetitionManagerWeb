/**
 * M-01 验证入口：真实 auth store + 真实控件包注册模块（含导入时的启动加载）。
 *
 * 由 tests/fix_verify/frontend/bundle.ps1 打包成单个 ESM 后，用 Node 直接 import。
 * import 顺序有语义：browser.mjs（环境）→ m01_boot.mjs（装 adapter）→ registerCustomWidgets
 * （它在导入时就会请求 /widget-packages，必须先装好 adapter）。
 */
import "../stubs/browser.mjs";
import browserStub from "../stubs/browser.mjs";

import { api, PACKAGE, state } from "./m01_boot.mjs";
// 侧效应导入：启动时自动拉取控件包（改前只此一次）
import "@/components/dashboard/registerCustomWidgets";

import { createPinia, setActivePinia } from "pinia";
import {
  getCustomWidget,
  isCustomType,
  listCustomWidgets,
} from "@/components/dashboard/types";
import { useAuthStore } from "@/stores/auth";

export {
  api,
  browserStub,
  createPinia,
  getCustomWidget,
  isCustomType,
  listCustomWidgets,
  PACKAGE,
  setActivePinia,
  state,
  useAuthStore,
};
