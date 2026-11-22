import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// В разработке Vite проксирует /api на Flask, поэтому браузер видит один origin —
// так же, как на сервере, где Flask сам раздаёт собранный интерфейс.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:5001", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false },
});
