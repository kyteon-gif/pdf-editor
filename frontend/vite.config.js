import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base: "/static/" 只在正式建置（npm run build）時需要，
// 因為那時編譯後的檔案會被放進 Flask 的 static/ 目錄，由 Flask serve。
// 開發模式（npm run dev）下 Vite 自己的 dev server 是用根路徑 "/" serve 檔案，
// 若這裡也套用 "/static/" 會讓所有資源請求多一層前綴，導致全部 404、畫面空白。
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/static/" : "/",
  build: {
    outDir: "../pdf_editor/static",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    // 開發模式下，API 請求轉發到 Flask
    // 若你的 Flask 是用其他 port 啟動（例如 5001），請同步修改這裡的 target
    proxy: {
      "/api": {
        target: "http://localhost:5001",
        changeOrigin: true,
      },
    },
  },
}));
