import { defineConfig } from '@playwright/test'

const reportDirectory = process.env.YANZHENG_BROWSER_REPORT_DIR || 'test-results'

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  retries: 0,
  timeout: 30000,
  reporter: [['list'], ['json', { outputFile: `${reportDirectory}/results.json` }]],
  outputDir: `${reportDirectory}/artifacts`,
  use: {
    baseURL: 'http://127.0.0.1:18083',
    headless: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    ...(process.env.YANZHENG_TEST_BROWSER ? { launchOptions: { executablePath: process.env.YANZHENG_TEST_BROWSER } } : {}),
  },
  projects: [
    { name: 'desktop', metadata: { viewport: '1440x1000' }, use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', metadata: { viewport: '390x844' }, use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    { name: 'tablet', metadata: { viewport: '768x1024' }, use: { viewport: { width: 768, height: 1024 }, hasTouch: true } },
  ],
  webServer: {
    command: 'python ../evaluation/browser_server.py',
    url: 'http://127.0.0.1:18083/api/health',
    reuseExistingServer: false,
    timeout: 30000,
  },
})
