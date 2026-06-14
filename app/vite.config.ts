import path from "path"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig({
  // Castle sets VITE_BASE to the gateway serve prefix at build time so absolute
  // asset URLs resolve at the subpath (castle-app is the root app → "/").
  base: process.env.VITE_BASE ?? "/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:9020",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
})
