/**
 * 轻量 HTML 净化：v-html 渲染前的最后一道防线。
 *
 * 公告等内容虽目前由开发者维护（可信），但一旦未来改为服务端下发/用户可控，
 * 直接 v-html 会带来存储型 XSS 风险。此处用浏览器原生 DOMParser 拦截常见向量：
 *   - 移除 SCRIPT/STYLE/IFRAME/OBJECT/EMBED/LINK/META/FORM/INPUT/BUTTON/BASE/SVG/MATH 等危险标签
 *   - 剥离所有 on* 事件处理器属性
 *   - 禁止 href/src/xlink:href/srcset 使用 javascript:/data:text/html/data:image/svg+xml/vbscript: 协议
 *   - 清洗 style 中的 expression()/javascript:/data:/url(javascript|data:) 向量
 * 不依赖第三方库，零运行时成本（仅在渲染公告时调用）。
 */
const BLOCKED_TAGS = [
  "SCRIPT",
  "STYLE",
  "IFRAME",
  "OBJECT",
  "EMBED",
  "LINK",
  "META",
  "FORM",
  "INPUT",
  "BUTTON",
  "BASE",
  "SVG",
  "MATH",
];

/** 危险 URI 协议（svg+xml 可携带可执行脚本，需一并拦截）。 */
function isDangerousUri(value: string): boolean {
  const v = value.trim().toLowerCase();
  return (
    v.startsWith("javascript:") ||
    v.startsWith("data:text/html") ||
    v.startsWith("data:image/svg+xml") ||
    v.startsWith("vbscript:")
  );
}

/** style 属性中的危险向量：expression / javascript: / data: / url(javascript|data:) 等。 */
function isDangerousStyle(value: string): boolean {
  const v = value.toLowerCase();
  return (
    v.includes("expression(") ||
    v.includes("javascript:") ||
    v.includes("data:text/html") ||
    v.includes("data:image/svg+xml") ||
    /url\(\s*(['"]?)(javascript:|data:)/i.test(v)
  );
}

export function sanitizeHtml(html: string): string {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");

  // 1) 移除危险标签（连同其内容）
  for (const tag of BLOCKED_TAGS) {
    doc.querySelectorAll(tag).forEach((el) => el.remove());
  }

  // 2) 剥离所有元素上的事件处理器与危险协议属性
  doc.body.querySelectorAll("*").forEach((el) => {
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      const value = attr.value; // 保留原始大小写用于协议判定
      const valueL = value.toLowerCase().trim();
      if (name.startsWith("on")) {
        el.removeAttribute(attr.name);
      } else if (
        name === "href" ||
        name === "src" ||
        name === "xlink:href"
      ) {
        if (isDangerousUri(valueL)) {
          el.removeAttribute(attr.name);
        }
      } else if (name === "srcset") {
        // srcset 为逗号分隔的多个 URI，逐段检测（取每段首个 token 作为 URI）
        const segs = value.split(",").map((s) => (s.trim().split(/\s+/)[0] || ""));
        if (segs.some((s) => isDangerousUri(s))) {
          el.removeAttribute(attr.name);
        }
      } else if (name === "style") {
        if (isDangerousStyle(value)) {
          el.removeAttribute(attr.name);
        }
      }
    }
  });

  return doc.body.innerHTML;
}
