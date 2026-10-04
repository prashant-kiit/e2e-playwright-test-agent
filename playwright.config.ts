import fs from 'fs';
import path from 'path';
import { defineConfig, devices, type Project } from '@playwright/test';

/**
 * Applications under test are discovered, not listed here.
 * Every folder apps/<app>/ with an app.json becomes one set of browser projects
 * named <app>-<browser>, running only apps/<app>/** against the app's baseURL.
 * Folders starting with "_" (e.g. apps/_template) are skipped.
 * To add an app, copy apps/_template — nothing in this file needs to change.
 */
const APPS_DIR = path.join(__dirname, 'apps');

const BROWSERS = {
  chromium: devices['Desktop Chrome'],
  firefox: devices['Desktop Firefox'],
  webkit: devices['Desktop Safari'],
  'mobile-chrome': devices['Pixel 7'],
};

function appProjects(): Project[] {
  const apps = fs
    .readdirSync(APPS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory() && !d.name.startsWith('_') && fs.existsSync(path.join(APPS_DIR, d.name, 'app.json')))
    .map((d) => d.name)
    .sort();

  return apps.flatMap((app) => {
    const { baseURL } = JSON.parse(fs.readFileSync(path.join(APPS_DIR, app, 'app.json'), 'utf8'));
    if (!baseURL) throw new Error(`apps/${app}/app.json: "baseURL" is required`);
    return Object.entries(BROWSERS).map(([browser, device]) => ({
      name: `${app}-${browser}`,
      testDir: path.join(APPS_DIR, app),
      use: { ...device, baseURL },
    }));
  });
}

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './apps',
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  /* open: 'never' so a failing local run doesn't block waiting on the report server */
  reporter: [['list'], ['html', { open: 'never' }]],
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Playwright's default is no limit; agents driving the browser over MCP would hang forever on a missing element */
    actionTimeout: 10_000,
    navigationTimeout: 15_000,

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',
  },

  /* <app>-chromium, <app>-firefox, <app>-webkit, <app>-mobile-chrome for every app.
   * The MCP *_setup_page tools default to the first project, so always pass `project`. */
  projects: appProjects(),
});
