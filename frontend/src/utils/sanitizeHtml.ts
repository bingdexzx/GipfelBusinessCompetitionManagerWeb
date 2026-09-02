/**
 * 轻量 HTML 净化：v-html 渲染前的最后一道防线。
 *
 * 公告等内容虽目前由开发者维护（可信），但一旦未来改为服务端下发/用户可控，
 * 直接 v-html 会带来存储型 XSS 风险。此处用浏览器原生 DOMParser 拦截常见向量：
 *   - 移除 <script>/<style>/<iframe>/<object>/<embed>/<link>/<meta>/<form>/<input>/<button> 等危险标签
 *   - 剥离所有 on* 事件处理器属性
 *   - 禁止 href/src 使用 javascript:/data:text/html 协议
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
];

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
      const value = attr.value.toLowerCase().trim();
      if (name.startsWith("on")) {
        el.removeAttribute(attr.name);
      } else if (
        (name === "href" || name === "src") &&
        (value.startsWith("javascript:") || value.startsWith("data:text/html"))
      ) {
        el.removeAttribute(attr.name);
      }
    }
  });

  return doc.body.innerHTML;
}
