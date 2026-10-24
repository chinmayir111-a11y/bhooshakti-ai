import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, host: true },
  build: {
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        // Keep the heavy map stacks out of the citizen bundle. They are only
        // imported from the lazily-loaded control room and replay pages.
        manualChunks(id) {
          if (id.includes('node_modules/maplibre-gl')) return 'maplibre'
          if (id.includes('node_modules/@deck.gl') || id.includes('node_modules/@luma.gl') || id.includes('node_modules/@loaders.gl') || id.includes('node_modules/@math.gl')) return 'deck'
          if (id.includes('node_modules/leaflet')) return 'leaflet'
        },
      },
    },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
})
