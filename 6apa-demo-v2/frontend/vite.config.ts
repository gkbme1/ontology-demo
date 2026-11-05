import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// v2 后端默认 8710，开发端口 5180，均避开原 Demo（8700 / 5173）。改端口用 .env。
const DEFAULT_API = 'http://localhost:8710'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      port: Number(env.VITE_DEV_PORT ?? 5180),
      host: true,
      proxy: { '/api': { target: env.VITE_API_PROXY || DEFAULT_API, changeOrigin: true } }
    },
    build: { chunkSizeWarningLimit: 1500 }
  }
})
