import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 管理端（03）：独立应用、独立会话；不生成 source map（03 §3.4/04 §9.3）。
export default defineConfig({
  plugins: [vue()],
  build: {
    sourcemap: false,
    target: 'es2020',
  },
  server: {
    port: 5175,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
