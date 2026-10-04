// spec: apps/saucedemo/specs/SCRUM-102-login-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

// The 'input_error' CSS class token is always present on these inputs; a validation
// error adds an additional 'error' token. This regex asserts specifically on that token.
const ERROR_CLASS = /(^|\s)error(\s|$)/;

test.describe('AC3 - Locked-out User', () => {
  test.beforeEach(async ({ page }) => {
    // 1. Navigate to '/'
    await page.goto('/');
  });

  test('Locked-out user sees the lockout error and remains on the login page', async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');

    // 2. Fill username with 'locked_out_user' and password with 'secret_sauce', click [data-test="login-button"]
    await username.fill('locked_out_user');
    await password.fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();

    // expect: URL remains '/' (no navigation to /inventory.html)
    await expect(page).toHaveURL('/');
    // expect: [data-test="error"] alert text is exactly 'Epic sadface: Sorry, this user has been locked out.'
    await expect(page.locator('[data-test="error"]')).toHaveText(
      'Epic sadface: Sorry, this user has been locked out.',
    );
    // expect: Both username and password fields carry the 'error' CSS class
    await expect(username).toHaveClass(ERROR_CLASS);
    await expect(password).toHaveClass(ERROR_CLASS);
  });

  test('Locked-out user cannot access the protected inventory page even via direct navigation', async ({
    page,
  }) => {
    // 1. Navigate to '/', attempt login with locked_out_user/secret_sauce and observe the lockout error
    await page.locator('[data-test="username"]').fill('locked_out_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    // expect: Lockout error shown, user remains unauthenticated
    await expect(page.locator('[data-test="error"]')).toHaveText(
      'Epic sadface: Sorry, this user has been locked out.',
    );

    // 2. Navigate directly to '/inventory.html'
    await page.goto('/inventory.html');

    // expect: Browser is redirected back to '/'
    await expect(page).toHaveURL('/');
    // expect: Error alert text is exactly "Epic sadface: You can only access '/inventory.html' when you are logged in."
    // (confirms the failed locked-out attempt did not create a session)
    await expect(page.locator('[data-test="error"]')).toHaveText(
      "Epic sadface: You can only access '/inventory.html' when you are logged in.",
    );
  });

  test('Locked-out error can be dismissed and the user can retry (and still fails)', async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');
    const loginButton = page.locator('[data-test="login-button"]');
    const error = page.locator('[data-test="error"]');

    // 1. Navigate to '/', submit locked_out_user/secret_sauce to trigger the lockout error
    await username.fill('locked_out_user');
    await password.fill('secret_sauce');
    await loginButton.click();
    // expect: Lockout error visible
    await expect(error).toHaveText('Epic sadface: Sorry, this user has been locked out.');

    // 2. Click [data-test="error-button"] to dismiss the error
    await page.locator('[data-test="error-button"]').click();
    // expect: Error alert disappears
    await expect(error).not.toBeVisible();
    // expect: 'error' CSS class removed from both fields
    await expect(username).not.toHaveClass(ERROR_CLASS);
    await expect(password).not.toHaveClass(ERROR_CLASS);
    // expect: Username/password text values remain in the inputs
    await expect(username).toHaveValue('locked_out_user');
    await expect(password).toHaveValue('secret_sauce');

    // 3. Click [data-test="login-button"] again without changing the fields
    await loginButton.click();
    // expect: The exact same lockout error reappears: 'Epic sadface: Sorry, this user has been locked out.'
    await expect(error).toHaveText('Epic sadface: Sorry, this user has been locked out.');
    // expect: User still remains on '/'
    await expect(page).toHaveURL('/');
  });
});
