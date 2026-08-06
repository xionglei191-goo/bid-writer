import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendTarget = process.env.BID_WRITER_API_TARGET || "http://127.0.0.1:8779";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": backendTarget,
      "/downloads": backendTarget,
    },
  },
});
