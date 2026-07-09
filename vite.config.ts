import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// USKMaker - config do Vite, seguindo o mesmo padrão usado no Ultimate
// Karaoke Player (porta fixa diferente - 1423 - para poder rodar os dois
// projetos Tauri ao mesmo tempo em dev, se precisar).
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1423,
    strictPort: true,
    watch: {
      // Não vigiar a pasta de build do Rust (src-tauri/target). Ela não tem
      // nada de frontend, e observá-la causava um crash EBUSY intermitente
      // no Windows: o Vite tentava dar "watch" no uskmaker.exe no exato
      // instante em que o cargo estava escrevendo/travando o arquivo
      // durante a compilação (erro real, 06/07/2026). Ignorar a pasta
      // resolve na raiz e ainda deixa o hot-reload do frontend intacto.
      ignored: ["**/src-tauri/**"],
    },
  },
  envPrefix: ["VITE_", "TAURI_"],
  build: {
    target: process.env.TAURI_PLATFORM === "windows" ? "chrome105" : "safari13",
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
});
