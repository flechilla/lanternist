import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app is served by FastAPI in production (`lanternist serve`), so it builds into the Python package.
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "../src/lanternist/api/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8420", changeOrigin: false } },
  },
});
