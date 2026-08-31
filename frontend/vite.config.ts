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
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/socket.io": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
      "/uploads": {
        target: "http://localhost:8000",
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
