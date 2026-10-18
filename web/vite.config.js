/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy the API paths to the backend so the browser sees one origin and the
// session cookie just works (no CORS, no cross-site cookie headaches).
const apiPaths = ["/auth", "/projects", "/targets", "/runs", "/artifacts", "/health"];
const proxy = Object.fromEntries(
  apiPaths.map((p) => [p, { target: "http://localhost:8000", changeOrigin: true }]),
);

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.js",
    css: false,
  },
});
