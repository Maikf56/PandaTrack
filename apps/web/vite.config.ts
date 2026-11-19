import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 04 §9.3：不生成 source map，不输出生产调试日志；客户端只调 /api/v1/*。
export default defineConfig({
  plugins: [vue()],
  build: {
    sourcemap: false,
    target: 'es2020',
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
