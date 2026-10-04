import { test, expect } from '@playwright/test';

test.describe('Test group', () => {
  test('seed', async ({ page }) => {
    // Start every agent session for the Playwright Practice Target on its home page.
    // No login: only /dashboard is protected, and SCRUM-201 tests the login itself.
    await page.goto('/');
    await expect(page.getByTestId('home-page')).toBeVisible();
    await expect(page.getByTestId('status-badge')).toHaveText('online');

    // generate code here.
  });
});
