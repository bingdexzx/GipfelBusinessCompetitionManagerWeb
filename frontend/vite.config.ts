import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

// 纯 Web 配置（已剥离 Electron）。
// 开发代理 /api 与 /socket.io 到 Django 后端（默认 8000），避免 CORS 预检开销。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        // 切到 Dart Sass 现代 API，消除 "legacy-js-api is deprecated" 弃用警告
        // （需 sass >= 1.71，本项目 1.77.6 满足；Vite 5 原生支持，无需 sass-embedded）
        api: "modern",
      },
    },
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      // 注意：target 必须用 127.0.0.1 而非 localhost。
      // Windows 上 localhost 优先解析到 IPv6 ::1，而 daphne 默认只监听 IPv4，
      // 代理先对 ::1 建连被 RST 再回退 IPv4，表现为「vite ws proxy error: read ECONNRESET」
      // 并触发 socket.io 反复重连。显式用 IPv4 可彻底消除该问题。
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/socket.io": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        ws: true,
      },
      "/uploads": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      // 后端管理后台 /admin/*：开发态同样需经网关（携带一次性令牌），
      // 否则 Vite 会按 SPA 路由兜底返回 index.html，导致管理后台在开发环境不可达。
      "/admin": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2020",
    chunkSizeWarningLimit: 2000,
  },
});
