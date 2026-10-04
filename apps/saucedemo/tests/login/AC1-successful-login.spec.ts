// spec: apps/saucedemo/specs/SCRUM-102-login-test-plan.md
// seed: apps/saucedemo/seed.spec.ts (NOT used here - these are login tests, each starts unauthenticated)

import { test, expect } from '@playwright/test';

test.describe('AC1 - Successful Login', () => {
  test('Login page displays all required elements', async ({ page }) => {
    // 1. Navigate to the base URL '/' with a fresh, unauthenticated browser context.
    await page.goto('/');
    await expect(page).toHaveURL('/');

    // 2. Assert the username field is visible and empty.
    const username = page.locator('[data-test="username"]');
    await expect(username).toBeVisible();
    await expect(username).toBeEmpty();

    // 3. Assert the password field is visible and empty.
    const password = page.locator('[data-test="password"]');
    await expect(password).toBeVisible();
    await expect(password).toBeEmpty();

    // 4. Assert the Login button is visible and enabled.
    const loginButton = page.locator('[data-test="login-button"]');
    await expect(loginButton).toBeVisible();
    await expect(loginButton).toBeEnabled();

    // 5. Assert the accepted usernames panel is visible and contains all six usernames.
    const credentialsPanel = page.locator('[data-test="login-credentials"]');
    await expect(credentialsPanel).toBeVisible();
    for (const user of ['standard_user', 'locked_out_user', 'problem_user', 'performance_glitch_user', 'error_user', 'visual_user']) {
      await expect(credentialsPanel).toContainText(user);
    }

    // 6. Assert the shared password panel is visible and contains 'secret_sauce'.
    const passwordPanel = page.locator('[data-test="login-password"]');
    await expect(passwordPanel).toBeVisible();
    await expect(passwordPanel).toContainText('secret_sauce');

    // 7. Assert no error alert is present on initial page load.
    await expect(page.locator('[data-test="error"]')).not.toBeVisible();
  });

  test('Successful login via Login button click with standard_user', async ({ page }) => {
    // 1. Navigate to '/'.
    await page.goto('/');

    // 2. Fill username with 'standard_user'.
    const username = page.locator('[data-test="username"]');
    await username.fill('standard_user');
    await expect(username).toHaveValue('standard_user');

    // 3. Fill password with 'secret_sauce'.
    const password = page.locator('[data-test="password"]');
    await password.fill('secret_sauce');
    await expect(password).toHaveValue('secret_sauce');

    // 4. Click the Login button.
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');
    await expect(page.locator('[data-test="error"]')).not.toBeVisible();
  });

  test('Successful login via Enter key in password field with standard_user', async ({ page }) => {
    // 1. Navigate to '/'.
    await page.goto('/');

    // 2. Fill username with 'standard_user'.
    await page.locator('[data-test="username"]').fill('standard_user');

    // 3. Click into the password field, type 'secret_sauce', then press Enter.
    const password = page.locator('[data-test="password"]');
    await password.fill('secret_sauce');
    await password.press('Enter');

    await expect(page).toHaveURL(/inventory\.html/);
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');
  });

  for (const user of ['problem_user', 'performance_glitch_user', 'error_user', 'visual_user']) {
    test(`Successful login for other accepted user: ${user}`, async ({ page }) => {
      // 1. Navigate to '/'.
      await page.goto('/');

      // 2. Fill username with the current user and password with 'secret_sauce', then click Login.
      await page.locator('[data-test="username"]').fill(user);
      await page.locator('[data-test="password"]').fill('secret_sauce');
      await page.locator('[data-test="login-button"]').click();

      // expect: navigation occurs to '/inventory.html' with Products title and no error.
      // Note: other defects for these users are explicitly out of scope for this story.
      await expect(page).toHaveURL(/inventory\.html/);
      await expect(page.locator('[data-test="title"]')).toHaveText('Products');
      await expect(page.locator('[data-test="error"]')).not.toBeVisible();
    });
  }
});
