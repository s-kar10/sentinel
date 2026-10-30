import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  use: {
    baseURL: 'http://127.0.0.1:18473',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: '../.venv/bin/python ../scripts/serve_browser_tests.py',
      url: 'http://127.0.0.1:18000/ready',
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 15_000 },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 18473 --strictPort',
      url: 'http://127.0.0.1:18473',
      env: { VITE_API_URL: 'http://127.0.0.1:18000' },
      reuseExistingServer: false,
    },
  ],
})
