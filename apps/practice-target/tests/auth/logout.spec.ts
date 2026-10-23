// spec: apps/practice-target/specs/SCRUM-201-auth-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect, type Page } from '@playwright/test';

async function login(page: Page) {
  await page.goto('/login');
  await page.getByTestId('login-username-input').fill('demo');
  await page.getByTestId('login-password-input').fill('password123');
  await page.getByTestId('login-submit-button').click();
  // Login has a ~1s simulated async delay; wait on the real outcome (URL change) rather than a fixed timeout.
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.describe('Logout and Nav Bar State', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('home-page')).toBeVisible();
    await expect(page.getByTestId('status-badge')).toHaveText('online');
  });

  test('Logging out from the dashboard revokes access and redirects to login with the from=/dashboard param', async ({ page }) => {
    // 1. Log in with demo/password123, arriving at /dashboard
    await login(page);

    // 2. Click nav-logout-button
    await page.getByTestId('nav-logout-button').click();

    // 3. Wait for and assert the final URL is '/login?from=%2Fdashboard'
    // Logging out immediately revokes the session; because /dashboard is protected and the user is
    // no longer authenticated, the app redirects to the login page with from=/dashboard.
    await expect(page).toHaveURL(/\/login\?from=%2Fdashboard$/);

    // 4. Assert login-form is visible and nav-link-login is shown in the nav bar (not nav-user-badge)
    await expect(page.getByTestId('login-form')).toBeVisible();
    await expect(page.getByTestId('nav-link-login')).toBeVisible();
    await expect(page.getByTestId('nav-user-badge')).not.toBeVisible();
  });

  test('After logout, re-visiting /dashboard directly redirects to login again (session fully revoked)', async ({ page }) => {
    // 1. Log in with demo/password123, arrive at /dashboard, then click nav-logout-button to log out
    await login(page);
    await page.getByTestId('nav-logout-button').click();
    await expect(page).toHaveURL(/\/login\?from=%2Fdashboard$/);

    // 2. Navigate directly to /dashboard again (fresh navigation)
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login\?from=%2Fdashboard$/);

    // 3. Assert dashboard-welcome is NOT present anywhere on the resulting page
    await expect(page.getByTestId('dashboard-welcome')).not.toBeVisible();
  });

  test('Logging out via the in-page dashboard logout button behaves the same as the nav bar logout button', async ({ page }) => {
    // 1. Log in with demo/password123, arriving at /dashboard
    await login(page);
    await expect(page.getByTestId('nav-logout-button')).toBeVisible();
    await expect(page.getByTestId('dashboard-logout-button')).toBeVisible();

    // 2. Click dashboard-logout-button (the one in the main content area, not the nav bar)
    await page.getByTestId('dashboard-logout-button').click();

    // 3. Assert the final URL is '/login?from=%2Fdashboard' and login-form is visible
    await expect(page).toHaveURL(/\/login\?from=%2Fdashboard$/);
    await expect(page.getByTestId('login-form')).toBeVisible();
  });

  test('Logged-out nav bar does not expose authenticated-only elements on any public page', async ({ page }) => {
    // 1. Starting from a fresh logged-out context, visit / (home)
    await page.goto('/');
    await expect(page.getByTestId('nav-link-login')).toBeVisible();
    await expect(page.getByTestId('nav-user-badge')).not.toBeVisible();
    await expect(page.getByTestId('nav-logout-button')).not.toBeVisible();

    // 2. Navigate to /forms and /table in turn (spot-check of public pages, per exploratory findings)
    for (const path of ['/forms', '/table']) {
      await page.goto(path);
      await expect(page.getByTestId('nav-link-login')).toBeVisible();
      await expect(page.getByTestId('nav-user-badge')).not.toBeVisible();
      await expect(page.getByTestId('nav-logout-button')).not.toBeVisible();
    }
  });
});
