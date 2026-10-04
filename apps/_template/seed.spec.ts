import { test, expect } from '@playwright/test';

test.describe('Test group', () => {
  test('seed', async ({ page }) => {
    // Bring the app to the state every agent session starts from (log in here if most pages need it).
    // Use relative URLs: baseURL comes from this app's app.json.
    await page.goto('/');
    await expect(page).toHaveURL(/.*/); // replace with a check that proves the app is ready

    // generate code here.
  });
});
