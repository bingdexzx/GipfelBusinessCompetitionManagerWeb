/**
 * 响应体解释（把 axios 的 `response.data` 归类为「信封成功 / 信封错误 / 二进制 / 非信封」）。
 *
 * 独立成模块的原因：这是纯判定逻辑，抽出来才能在 Node 侧用真实代码跑单测
 * （审计 F-01：blob 下载与其它非 `{code,message,data}` 信封的 2xx 响应被判为失败）。
 */
export type ResponseInterpretation =
  | { kind: "binary"; value: unknown }
  | { kind: "error"; message: string }
  | { kind: "data"; value: unknown };

/** 是否为二进制/文件下载响应（Blob / ArrayBuffer / TypedArray，含类 Blob 鸭子类型）。 */
export function isBinaryPayload(data: unknown): boolean {
  if (data == null) return false;
  if (typeof Blob !== "undefined" && data instanceof Blob) return true;
  if (typeof ArrayBuffer !== "undefined") {
    if (data instanceof ArrayBuffer) return true;
    if (ArrayBuffer.isView(data)) return true;
  }
  const o = data as { size?: unknown; slice?: unknown; type?: unknown };
  return (
    typeof o.size === "number" &&
    typeof o.slice === "function" &&
    typeof o.type === "string"
  );
}

/** 是否为后端统一信封 `{code, message, data}`（三键齐全才判定）。 */
export function isApiEnvelope(data: unknown): boolean {
  if (data == null || typeof data !== "object") return false;
  const o = data as Record<string, unknown>;
  return "code" in o && "message" in o && "data" in o;
}

/**
 * 解释响应体。
 *
 * 判定顺序（改前的实现只保留了最后一条，导致 blob 下载与非信封 2xx 全被判失败）：
 * 1. 二进制/文件下载（responseType: "blob"/"arraybuffer"）→ `binary`，调用方原样取用；
 * 2. 带 `code` 字段的对象 → 按统一信封语义处理（`code !== 0` 即错误，含 message 缺失兜底）；
 * 3. 其余（空响应体、裸数组、字符串等非信封 2xx）→ `data` 原样返回，不再一律判失败。
 */
export function interpretResponse(data: unknown): ResponseInterpretation {
  if (isBinaryPayload(data)) {
    return { kind: "binary", value: data };
  }
  if (data != null && typeof data === "object" && "code" in (data as Record<string, unknown>)) {
    const res = data as { code?: unknown; message?: unknown; data?: unknown };
    if (res.code !== 0) {
      return {
        kind: "error",
        message: typeof res.message === "string" && res.message ? res.message : "请求失败",
      };
    }
    return { kind: "data", value: res.data };
  }
  return { kind: "data", value: data };
}
