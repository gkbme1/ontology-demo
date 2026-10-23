import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // 代理目标与前端端口全部走环境变量，不在代码里写死
  const proxyTarget = env.VITE_API_PROXY || 'http://localhost:8800'
  const devPort = Number(env.VITE_DEV_PORT || 5174)

  return {
    plugins: [vue()],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: {
      port: devPort,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          // SSE 必须关闭缓冲，否则执行过程面板会一次性蹦出来
          configure: (proxy) => {
            proxy.on('proxyRes', (proxyRes) => {
              proxyRes.headers['cache-control'] = 'no-cache, no-transform'
            })
          },
        },
      },
    },
  }
})
