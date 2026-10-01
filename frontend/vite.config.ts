import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = process.env.PDE_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", proxy: { "/api": api } },
  build: { chunkSizeWarningLimit: 5000 },
});
