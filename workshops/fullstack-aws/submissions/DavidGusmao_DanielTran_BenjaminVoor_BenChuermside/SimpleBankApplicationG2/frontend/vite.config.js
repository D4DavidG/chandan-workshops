import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies /api to the Python backend, so the browser only ever
// talks to one origin and no CORS or base-URL configuration is needed while
// developing.
//
// Default target is 127.0.0.1:8000. If you run the backend somewhere else
// (python server.py --port 9000), point this at it without editing the file:
//
//   bash:        VITE_API_TARGET=http://127.0.0.1:9000 npm run dev
//   PowerShell:  $env:VITE_API_TARGET = "http://127.0.0.1:9000"; npm run dev
const target = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target,
        changeOrigin: true,
      },
    },
  },
  plugins: [react()],
})
