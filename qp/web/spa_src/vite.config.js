import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig(({ command }) => ({
  // 生产部署挂载在 qp 8080 /proto/ 下; dev 保持根路径
  base: command === 'build' ? '/proto/' : '/',
  plugins: [vue(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // 收编后端: qp FastAPI (:8080) 原生 /api/v1 + /api/stocks 端点
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true },
    },
  },
}));
