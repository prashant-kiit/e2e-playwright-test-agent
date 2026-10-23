// spec: apps/practice-target/specs/SCRUM-201-auth-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect, type Page } from '@playwright/test';

async function login(page: Page) {
  await page.getByTestId('login-username-input').fill('demo');
  await page.getByTestId('login-password-input').fill('password123');
  await page.getByTestId('login-submit-button').click();
  // Login has a ~1s simulated async delay; wait on the real outcome (URL change) rather than a fixed timeout.
  await expect(page).toHaveURL(/\/dashboard$/);
}

test.describe('Authentication - Happy Path and UI State', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('home-page')).toBeVisible();
    await expect(page.getByTestId('status-badge')).toHaveText('online');
  });

  test('Successful login with valid credentials lands on dashboard with full post-login UI', async ({ page }) => {
    // 1. Start from the seeded home page (logged out, fresh context). Navigate to /login.
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: 'Log in' })).toBeVisible();
    await expect(page.getByTestId('login-form')).toBeVisible();

    // 2. Assert the nav bar shows nav-link-login and does NOT show nav-user-badge or nav-logout-button
    await expect(page.getByTestId('nav-link-login')).toBeVisible();
    await expect(page.getByTestId('nav-user-badge')).not.toBeVisible();
    await expect(page.getByTestId('nav-logout-button')).not.toBeVisible();

    // 3. Fill login-username-input with 'demo'
    await page.getByTestId('login-username-input').fill('demo');
    await expect(page.getByTestId('login-username-input')).toHaveValue('demo');

    // 4. Fill login-password-input with 'password123'
    await page.getByTestId('login-password-input').fill('password123');
    await expect(page.getByTestId('login-password-input')).toHaveValue('password123');

    // 5. Click login-submit-button
    await page.getByTestId('login-submit-button').click();

    // 6. Wait for the URL to become /dashboard (async login delay handled by auto-waiting assertion)
    await expect(page).toHaveURL(/\/dashboard$/);

    // 7. Assert dashboard-welcome contains the text 'Welcome back, demo.'
    await expect(page.getByTestId('dashboard-welcome')).toHaveText('Welcome back, demo.');

    // 8. Assert nav-user-badge is visible and contains text 'demo'
    await expect(page.getByTestId('nav-user-badge')).toBeVisible();
    await expect(page.getByTestId('nav-user-badge')).toContainText('demo');

    // 9. Assert nav-logout-button is visible with accessible name 'Log out'
    await expect(page.getByTestId('nav-logout-button')).toBeVisible();
    await expect(page.getByTestId('nav-logout-button')).toHaveAccessibleName('Log out');

    // 10. Assert nav-link-login is no longer present in the nav bar
    await expect(page.getByTestId('nav-link-login')).not.toBeVisible();

    // 11. Assert dashboard-page and dashboard-session-expiry are visible
    await expect(page.getByTestId('dashboard-page')).toBeVisible();
    await expect(page.getByTestId('dashboard-session-expiry')).toBeVisible();
    await expect(page.getByTestId('dashboard-session-expiry')).not.toBeEmpty();

    // 12. Assert dashboard-logout-button is also visible in the main content area
    await expect(page.getByTestId('dashboard-logout-button')).toBeVisible();
  });

  test('Logged-in state persists across in-app navigation to other public pages', async ({ page }) => {
    // 1. Log in with demo/password123 via /login as in the happy-path test, arriving at /dashboard
    await page.goto('/login');
    await login(page);

    // 2. Click nav-link-home to navigate to the home page
    await page.getByTestId('nav-link-home').click();
    await expect(page).toHaveURL('/');

    // 3. Assert nav-user-badge and nav-logout-button are still visible on the home page
    await expect(page.getByTestId('nav-user-badge')).toBeVisible();
    await expect(page.getByTestId('nav-logout-button')).toBeVisible();

    // 4. Navigate back to /dashboard via nav-link-dashboard
    await page.getByTestId('nav-link-dashboard').click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByTestId('dashboard-welcome')).toBeVisible();
  });
});
