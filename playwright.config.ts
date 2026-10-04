import { defineConfig, devices } from '@playwright/test';

/**
 * Read environment variables from file.
 * https://github.com/motdotla/dotenv
 */
// import dotenv from 'dotenv';
// import path from 'path';
// dotenv.config({ path: path.resolve(__dirname, '.env') });

/* Applications under test. Each app has its own test folder (tests/<app>/, seed included),
 * and its projects run only that folder against the app's own baseURL. */
const SAUCEDEMO_BASE_URL = 'https://www.saucedemo.com';
const SAUCEDEMO_TESTS = '**/saucedemo/**/*.spec.ts';
const PRACTICE_BASE_URL = 'https://custom-test-target-app.vercel.app';
const PRACTICE_TESTS = '**/practice-target/**/*.spec.ts';

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './tests',
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

  /* One set of browser projects per application under test, each with its own baseURL.
   * SauceDemo projects keep their original names and `chromium` must stay first:
   * the MCP *_setup_page tools use the first project unless `project` is passed. */
  projects: [
    {
      name: 'chromium',
      testMatch: SAUCEDEMO_TESTS,
      use: { ...devices['Desktop Chrome'], baseURL: SAUCEDEMO_BASE_URL },
    },

    {
      name: 'firefox',
      testMatch: SAUCEDEMO_TESTS,
      use: { ...devices['Desktop Firefox'], baseURL: SAUCEDEMO_BASE_URL },
    },

    {
      name: 'webkit',
      testMatch: SAUCEDEMO_TESTS,
      use: { ...devices['Desktop Safari'], baseURL: SAUCEDEMO_BASE_URL },
    },

    /* Test against mobile viewports. */
    {
      name: 'Mobile Chrome',
      testMatch: SAUCEDEMO_TESTS,
      use: { ...devices['Pixel 7'], baseURL: SAUCEDEMO_BASE_URL },
    },

    /* Playwright Practice Target (stories SCRUM-201..208): its own baseURL and test folder. */
    {
      name: 'practice-chromium',
      testMatch: PRACTICE_TESTS,
      use: { ...devices['Desktop Chrome'], baseURL: PRACTICE_BASE_URL },
    },
    {
      name: 'practice-firefox',
      testMatch: PRACTICE_TESTS,
      use: { ...devices['Desktop Firefox'], baseURL: PRACTICE_BASE_URL },
    },
    {
      name: 'practice-webkit',
      testMatch: PRACTICE_TESTS,
      use: { ...devices['Desktop Safari'], baseURL: PRACTICE_BASE_URL },
    },
    {
      name: 'practice-mobile-chrome',
      testMatch: PRACTICE_TESTS,
      use: { ...devices['Pixel 7'], baseURL: PRACTICE_BASE_URL },
    },
    // {
    //   name: 'Mobile Safari',
    //   use: { ...devices['iPhone 12'] },
    // },

    /* Test against branded browsers. */
    // {
    //   name: 'Microsoft Edge',
    //   use: { ...devices['Desktop Edge'], channel: 'msedge' },
    // },
    // {
    //   name: 'Google Chrome',
    //   use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    // },
  ],

  /* Run your local dev server before starting the tests */
  // webServer: {
  //   command: 'npm run start',
  //   url: 'http://localhost:3000',
  //   reuseExistingServer: !process.env.CI,
  // },
});
