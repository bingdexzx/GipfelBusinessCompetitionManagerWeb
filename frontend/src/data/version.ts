/** 客户端版本号（真源：项目根目录 VERSION.json，构建时由 Vite define 注入）。 */
declare const __APP_VERSION__: string;
export const APP_VERSION: string = typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "0.0.0";