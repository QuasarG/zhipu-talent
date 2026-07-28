import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

export default defineConfig(({ command }) => ({
  // 构建产物由 Flask 挂在 /static/dist/ 下，CSS 内字体等 URL 必须带此前缀
  base: command === "build" ? "/static/dist/" : "/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8502",
      "/health": "http://127.0.0.1:8502",
    },
  },
  build: {
    outDir: "../agi_talent_radar/web/static/dist",
    emptyOutDir: true,
  },
}));