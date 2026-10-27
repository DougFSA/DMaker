import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// Servidor da API (`dmaker ui`) para onde o `npm run dev` repassa /api. Troque com DMAKER_API quando
// o dmaker ui estiver em outra porta.
const apiTarget = process.env.DMAKER_API ?? 'http://127.0.0.1:8773'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5174,
    strictPort: true,
    // a Poppins vive em assets/fonts, na raiz do repositório, fora da pasta frontend/
    fs: { allow: ['..'] },
    proxy: { '/api': { target: apiTarget, changeOrigin: false } },
  },
  build: {
    // o FastAPI serve esta pasta em "/" (ver ui/server.py); ela é artefato de build, fica fora do git
    outDir: '../src/dmaker/ui/dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.spec.ts'],
    restoreMocks: true,
    // a primeira navegação compila as telas carregadas sob demanda; em máquina ocupada passa dos 5 s padrão
    testTimeout: 30000,
  },
})
