import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    // Needed so the Vite dev server picks up file changes from a bind mount
    // inside Docker on Windows/macOS.
    watch: { usePolling: true },
  },
})
