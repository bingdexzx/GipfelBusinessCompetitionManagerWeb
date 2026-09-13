/**
 * F-06 验证入口：真实 auth store + 真实 request 层（含内存 memo）。
 *
 * 由 tests/fix_verify/frontend/bundle.ps1 打包成单个 ESM 后，用 Node 直接 import。
 * browser.mjs 必须排在最前：其余模块顶层会读 window / localStorage。
 */
import "../stubs/browser.mjs";

import { createPinia, setActivePinia } from "pinia";

import api from "@/api";
import { resetRequestMemo } from "@/api/request";
import { useAuthStore } from "@/stores/auth";
import {
  getAccountItem,
  removeAccountItem,
  setAccountItem,
  setActiveUser,
} from "@/utils/accountStorage";

export {
  api,
  createPinia,
  getAccountItem,
  removeAccountItem,
  resetRequestMemo,
  setAccountItem,
  setActiveUser,
  setActivePinia,
  useAuthStore,
};
