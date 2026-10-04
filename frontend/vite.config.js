import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 중 FastAPI(127.0.0.1:8000)로 /api 요청을 중계해 CORS 없이 동작하게 한다.
    // 백엔드 코드(api/*)는 건드리지 않는다 — 프런트엔드 전용 설정.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/setupTests.js',
  },
})
