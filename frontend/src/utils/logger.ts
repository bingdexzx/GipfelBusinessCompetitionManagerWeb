/** 简易日志器：统一带前缀输出到控制台。 */
export const logger = {
  info: (...args: unknown[]) => console.log("[Gipfel]", ...args),
  warn: (...args: unknown[]) => console.warn("[Gipfel]", ...args),
  error: (...args: unknown[]) => console.error("[Gipfel]", ...args),
  debug: (...args: unknown[]) => {
    if (import.meta.env.DEV) console.debug("[Gipfel]", ...args);
  },
};
