import { defineConfig, devices } from '@playwright/test'

// End-to-end tests drive a real browser against the running app.
// They need the backend API (port 8000), the ingestion worker and Ollama running;
// Playwright starts the Vite dev server itself.
export default defineConfig({
  testDir: './e2e',
  timeout: 240_000,
  expect: { timeout: 120_000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    ...devices['Desktop Chrome'],
    viewport: { width: 1360, height: 860 },
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
  },
})
