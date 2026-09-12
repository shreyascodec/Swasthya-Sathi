import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The FastAPI backend runs on :8000. Proxy /api there so the browser talks to a
// single origin (no CORS in dev) and the same relative paths work in a build.
// Avatar mesh/anims also go through the backend's no-store handler — Vite's
// static public/ serve can 304 on revalidate, which breaks three.js GLTFLoader.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/avatar': 'http://localhost:8000',
    },
  },
})
