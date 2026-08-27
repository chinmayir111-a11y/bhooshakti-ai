import { defineConfig } from 'vitest/config'

// Only the pure offline-queue logic is unit-tested here; the React Native
// screens are exercised by running the app.
export default defineConfig({
  test: { include: ['src/offline/*.test.ts'], environment: 'node' },
})
