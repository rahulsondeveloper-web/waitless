import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests. Uses the installed Microsoft Edge (no browser download needed on Windows).
 *   npm run e2e
 * Starts (or reuses) the FastAPI backend on :8000 and the Angular dev server on :4200.
 * Tests create uniquely named restaurants/customers in the development database.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  // The dev server serves unbundled modules; give assertions room and limit parallel browsers.
  expect: { timeout: 10_000 },
  workers: 2,
  fullyParallel: true,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:4200',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Edge'], channel: 'msedge' } },
    { name: 'mobile', use: { ...devices['Pixel 7'], channel: 'msedge' } },
  ],
  webServer: [
    {
      command: '.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000',
      cwd: '../backend',
      url: 'http://127.0.0.1:8000/api/v1/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: 'npm start',
      url: 'http://localhost:4200',
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
