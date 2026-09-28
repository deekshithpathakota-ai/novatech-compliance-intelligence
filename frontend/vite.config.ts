import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { fileURLToPath } from "node:url";

const devProxy = { "/api": { target: process.env.VITE_API_PROXY ?? "http://localhost:8000", changeOrigin: true } };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(path.dirname(fileURLToPath(import.meta.url)), "src") } },
  // Dev only: /api is proxied to the local backend. Production builds call VITE_API_URL directly (see src/lib/api.ts).
  server: { port: 5173, proxy: devProxy },
  preview: { port: 4173, proxy: devProxy }, // `npm run preview` of a build made without VITE_API_URL
});
