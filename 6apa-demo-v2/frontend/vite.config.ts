import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { viteSingleFile } from 'vite-plugin-singlefile'
import { fileURLToPath, URL } from 'node:url'

// v2 后端默认 8710，开发端口 5180，均避开原 Demo（8700 / 5173）。改端口用 .env。
const DEFAULT_API = 'http://localhost:8710'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    // --mode single：把 JS / CSS 全部内联成一个 index.html（单文件版，数据由 backend/tools/export_static.py 注入）
    plugins: mode === 'single' ? [vue(), viteSingleFile()] : [vue()],
    resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
    server: {
      port: Number(env.VITE_DEV_PORT ?? 5180),
      host: true,
      proxy: { '/api': { target: env.VITE_API_PROXY || DEFAULT_API, changeOrigin: true } }
    },
    build: mode === 'single'
      ? { outDir: 'dist-single', emptyOutDir: true, chunkSizeWarningLimit: 4000 }
      : { chunkSizeWarningLimit: 1500 }
  }
})
