import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  build: {
    outDir: '../src/openclaw_video/webdist',
    emptyOutDir: true,
    assetsDir: 'assets',
    target: 'es2020',
    sourcemap: false,
  },
});
