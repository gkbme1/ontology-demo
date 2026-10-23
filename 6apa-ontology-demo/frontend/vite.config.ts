import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 本体服务地址。改端口优先用 .env 里的 VITE_API_PROXY，不要改这里的默认值。
const DEFAULT_API = 'http://localhost:8700'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [vue()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      port: Number(env.VITE_DEV_PORT ?? 5173),
      // 开发期直接把 /api 代理到本体服务，前端无需处理跨域
      proxy: { '/api': { target: env.VITE_API_PROXY || DEFAULT_API, changeOrigin: true } }
    }
  }
})
