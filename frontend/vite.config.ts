import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build lands directly in the backend's static directory so a single
// container serves both the API and the compiled application.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8080",
        changeOrigin: true,
      },
    },
  },
});
