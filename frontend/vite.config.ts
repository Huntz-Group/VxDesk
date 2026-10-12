import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { inspectAttr } from 'kimi-plugin-inspect-react'

// https://vite.dev/config/
// server.host / server.port remain settable from CLI args (vite handles this natively).
const proxy = {
  '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
  '/ws': { target: 'ws://127.0.0.1:8765', ws: true },
} as const;

export default defineConfig({
  base: './',
  plugins: [inspectAttr(), react()],
  server: {
    port: 3000,
    proxy,
  },
  preview: {
    proxy,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
