/**
 * 最小浏览器环境桩（Node 侧跑真实前端模块用）。
 *
 * 只实现被测代码真正用到的部分：
 *   - window：事件监听/派发（auth store 监听 auth:kicked、request 监听 server:changed）、
 *     location.hash（401 跳转登录页）、localStorage 转发。
 *   - localStorage / CustomEvent。
 *   - **不提供 indexedDB**：本地全量副本层的 cacheGet/cacheSet 在无 IndexedDB 时会静默降级，
 *     于是每次 GET 都真实走「网络 → memo 写入」这条路径，测试无需模拟 IndexedDB。
 *
 * 必须在其它模块之前 import（ESM 按 import 顺序求值），否则模块顶层读 window/localStorage 会抛错。
 */

class FakeEventTarget {
  constructor() {
    this._listeners = new Map();
  }

  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, new Set());
    this._listeners.get(type).add(fn);
  }

  removeEventListener(type, fn) {
    this._listeners.get(type)?.delete(fn);
  }

  dispatchEvent(evt) {
    const type = evt?.type;
    const set = this._listeners.get(type);
    if (set) for (const fn of Array.from(set)) fn.call(this, evt);
    return true;
  }
}

class FakeStorage {
  constructor() {
    this._map = new Map();
  }

  getItem(k) {
    const v = this._map.get(String(k));
    return v === undefined ? null : v;
  }

  setItem(k, v) {
    this._map.set(String(k), String(v));
  }

  removeItem(k) {
    this._map.delete(String(k));
  }

  clear() {
    this._map.clear();
  }

  key(i) {
    return Array.from(this._map.keys())[i] ?? null;
  }

  get length() {
    return this._map.size;
  }
}

if (typeof globalThis.CustomEvent === "undefined") {
  globalThis.CustomEvent = class CustomEvent {
    constructor(type, init = {}) {
      this.type = type;
      this.detail = init.detail;
    }
  };
}

const storage = new FakeStorage();

if (typeof globalThis.localStorage === "undefined") {
  globalThis.localStorage = storage;
}
if (typeof globalThis.sessionStorage === "undefined") {
  globalThis.sessionStorage = new FakeStorage();
}

if (typeof globalThis.window === "undefined") {
  const win = new FakeEventTarget();
  win.location = {
    href: "http://127.0.0.1:5173/",
    origin: "http://127.0.0.1:5173",
    protocol: "http:",
    host: "127.0.0.1:5173",
    hostname: "127.0.0.1",
    port: "5173",
    pathname: "/",
    hash: "",
    search: "",
    reload() {
      browserStub.reloads += 1;
    },
  };
  win.localStorage = globalThis.localStorage;
  win.sessionStorage = globalThis.sessionStorage;
  win.navigator = { userAgent: "node-fix-verify" };
  win.setTimeout = setTimeout;
  win.clearTimeout = clearTimeout;
  win.setInterval = setInterval;
  win.clearInterval = clearInterval;
  globalThis.window = win;
}

export const browserStub = {
  storage,
  window: globalThis.window,
  /** window.location.reload() 调用次数（控件包变更广播会触发整页刷新）。 */
  reloads: 0,
  /** 测试可覆盖：模拟 component.js 执行（真实环境里它会设置 window.__widget_module__）。 */
  onScriptLoad: () => {},
};

// document 桩：控件包通过 <script src=componentUrl> 加载，onload 后读 window.__widget_module__
if (typeof globalThis.document === "undefined") {
  const head = {
    children: [],
    appendChild(el) {
      this.children.push(el);
      browserStub.onScriptLoad(el.src);
      if (typeof el.onload === "function") el.onload();
    },
  };
  globalThis.document = {
    head,
    createElement(tag) {
      return { tagName: String(tag).toUpperCase(), src: "", onload: null, onerror: null };
    },
  };
  globalThis.window.document = globalThis.document;
}

export default browserStub;
