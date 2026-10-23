// spec: apps/practice-target/specs/SCRUM-201-auth-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Routing Boundary Check', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('home-page')).toBeVisible();
    await expect(page.getByTestId('status-badge')).toHaveText('online');
  });

  test('Unknown path returns a client-side 404 page (not an HTTP error) and does not affect auth state', async ({ page }) => {
    // 1. From a fresh logged-out context, navigate directly to an unknown path such as /this-path-does-not-exist
    // Per agentNotes, the app returns HTTP 200 and renders a client-side 404 page; assert on page content only.
    await page.goto('/this-path-does-not-exist');

    // 2. Assert not-found-page is visible with heading text '404 — Page not found'
    await expect(page.getByTestId('not-found-page')).toBeVisible();
    await expect(page.getByTestId('not-found-page')).toContainText('404 — Page not found');

    // 3. Assert the nav bar still correctly shows nav-link-login (logged-out state is unaffected)
    await expect(page.getByTestId('nav-link-login')).toBeVisible();

    // 4. Click not-found-home-link
    await page.getByTestId('not-found-home-link').click();
    await expect(page).toHaveURL('/');
    await expect(page.getByTestId('home-page')).toBeVisible();

    // 5. As a contrast check, log in with demo/password123 first, then navigate to the same unknown
    // path /this-path-does-not-exist while authenticated
    await page.goto('/login');
    await page.getByTestId('login-username-input').fill('demo');
    await page.getByTestId('login-password-input').fill('password123');
    await page.getByTestId('login-submit-button').click();
    await expect(page).toHaveURL(/\/dashboard$/);

    await page.goto('/this-path-does-not-exist');
    await expect(page.getByTestId('not-found-page')).toBeVisible();
    await expect(page.getByTestId('nav-user-badge')).toBeVisible();
  });
});
