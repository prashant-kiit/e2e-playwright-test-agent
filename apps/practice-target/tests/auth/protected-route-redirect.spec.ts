// spec: apps/practice-target/specs/SCRUM-201-auth-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Protected Route Redirect (AC2)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('home-page')).toBeVisible();
    await expect(page.getByTestId('status-badge')).toHaveText('online');
  });

  test('Direct deep link to /dashboard while logged out redirects to /login with from param', async ({ page }) => {
    // 1. Starting from a fresh logged-out context, navigate directly to /dashboard (deep link, not via in-app nav click)
    await page.goto('/dashboard');

    // 2. Assert the final URL is exactly '/login?from=%2Fdashboard'
    await expect(page).toHaveURL(/\/login\?from=%2Fdashboard$/);

    // 3. Assert login-form is visible and dashboard-page is NOT present anywhere on the page
    await expect(page.getByTestId('login-form')).toBeVisible();
    await expect(page.getByTestId('dashboard-page')).not.toBeVisible();
  });

  test('Logging in from the redirected state returns the user to the originally requested /dashboard', async ({ page }) => {
    // 1. Navigate directly to /dashboard while logged out, landing on /login?from=%2Fdashboard
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login\?from=%2Fdashboard$/);

    // 2. Fill login-username-input with 'demo' and login-password-input with 'password123'
    await page.getByTestId('login-username-input').fill('demo');
    await page.getByTestId('login-password-input').fill('password123');

    // 3. Click login-submit-button
    await page.getByTestId('login-submit-button').click();

    // 4. Wait for the URL to become /dashboard (not /login) — async login delay handled by auto-waiting assertion
    await expect(page).toHaveURL(/\/dashboard$/);

    // 5. Assert dashboard-welcome contains 'Welcome back, demo.' and nav-user-badge is visible
    await expect(page.getByTestId('dashboard-welcome')).toContainText('Welcome back, demo.');
    await expect(page.getByTestId('nav-user-badge')).toBeVisible();
  });

  test('Protected-route redirect also applies when the from path has query-string-unsafe characters (boundary check using /dashboard only)', async ({ page }) => {
    // 1. Note: /dashboard is the ONLY protected page in this app, so this scenario is scoped to confirming
    // the encoding of the single protected path rather than testing multiple protected routes.

    // 2. Navigate directly to /dashboard while logged out
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/login\?from=%2Fdashboard$/);

    // 3. Assert the raw query string value of 'from' decodes to exactly '/dashboard'
    const fromParam = new URL(page.url()).searchParams.get('from');
    expect(fromParam).toBe('/dashboard');
  });
});
