/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy the API paths to the backend so the browser sees one origin and the
// session cookie just works (no CORS, no cross-site cookie headaches).
const apiPaths = [
  "/auth",
  "/projects",
  "/targets",
  "/runs",
  "/artifacts",
  "/revisions",
  "/apps",
  "/prompts",
  "/settings",
  // P5-04's quota panel. Adding a route to api.js and forgetting this list does
  // not 404 -- it answers 200 with the SPA shell, and a caller that degrades
  // gracefully renders nothing at all. `test_api_proxy_paths.py` asserts this
  // list and nginx's against api.js so the next one fails a test instead.
  "/usage",
  "/health",
];
// API paths sit at the root and collide with SPA client routes (/settings,
// /projects, ...). `bypass` serves the SPA for full-page navigations (Accept:
// text/html) and proxies fetch/XHR/SSE calls to the backend.
const proxy = Object.fromEntries(
  apiPaths.map((p) => [
    p,
    {
      target: "http://localhost:8000",
      changeOrigin: true,
      bypass: (req) =>
        (req.headers.accept || "").includes("text/html") ? "/index.html" : undefined,
    },
  ]),
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
