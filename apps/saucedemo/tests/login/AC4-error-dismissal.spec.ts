// spec: apps/saucedemo/specs/SCRUM-102-login-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

// The 'input_error' CSS class token is always present on these inputs; a validation
// error adds an additional 'error' token. This regex asserts specifically on that token.
const ERROR_CLASS = /(^|\s)error(\s|$)/;

test.describe('AC4 - Error Message Dismissal', () => {
  test.beforeEach(async ({ page }) => {
    // 1. Navigate to '/'
    await page.goto('/');
  });

  test("Dismissing the 'Username is required' error clears the alert and field error styling", async ({
    page,
  }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');
    const error = page.locator('[data-test="error"]');

    // 1. Navigate to '/' and click [data-test="login-button"] with empty fields to trigger 'Username is required'
    await page.locator('[data-test="login-button"]').click();
    // expect: Error alert and field error classes present
    await expect(error).toHaveText('Epic sadface: Username is required');
    await expect(username).toHaveClass(ERROR_CLASS);
    await expect(password).toHaveClass(ERROR_CLASS);

    // 2. Click [data-test="error-button"] (the X icon)
    await page.locator('[data-test="error-button"]').click();
    // expect: [data-test="error"] alert is no longer present in the DOM/visible
    await expect(error).not.toBeVisible();
    // expect: Neither username nor password field carries the 'error' CSS class any more
    await expect(username).not.toHaveClass(ERROR_CLASS);
    await expect(password).not.toHaveClass(ERROR_CLASS);
  });

  test("Dismissing the 'Password is required' error clears the alert", async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');
    const error = page.locator('[data-test="error"]');

    // 1. Navigate to '/', fill username only, submit to trigger 'Password is required'
    await username.fill('standard_user');
    await page.locator('[data-test="login-button"]').click();
    // expect: Error alert visible
    await expect(error).toHaveText('Epic sadface: Password is required');

    // 2. Click [data-test="error-button"]
    await page.locator('[data-test="error-button"]').click();
    // expect: Error alert disappears
    await expect(error).not.toBeVisible();
    // expect: Field error classes cleared
    await expect(username).not.toHaveClass(ERROR_CLASS);
    await expect(password).not.toHaveClass(ERROR_CLASS);
    // expect: Username value 'standard_user' is still present in the username field
    await expect(username).toHaveValue('standard_user');
  });

  test('Dismissing the credential-mismatch error preserves previously typed field values', async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');
    const error = page.locator('[data-test="error"]');

    // 1. Navigate to '/', fill username 'bad_user' and password 'bad_pass', submit to trigger the mismatch error
    await username.fill('bad_user');
    await password.fill('bad_pass');
    await page.locator('[data-test="login-button"]').click();
    // expect: Error alert 'Epic sadface: Username and password do not match any user in this service' visible
    await expect(error).toHaveText('Epic sadface: Username and password do not match any user in this service');

    // 2. Click [data-test="error-button"]
    await page.locator('[data-test="error-button"]').click();
    // expect: Error alert disappears
    await expect(error).not.toBeVisible();
    // expect: Username field value is still 'bad_user'
    await expect(username).toHaveValue('bad_user');
    // expect: Password field value is still 'bad_pass'
    await expect(password).toHaveValue('bad_pass');
    // expect: Error CSS class removed from both fields
    await expect(username).not.toHaveClass(ERROR_CLASS);
    await expect(password).not.toHaveClass(ERROR_CLASS);
  });

  test('Dismissing the locked-out error clears the alert and allows editing the form', async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');
    const error = page.locator('[data-test="error"]');

    // 1. Navigate to '/', submit locked_out_user/secret_sauce to trigger the lockout error
    await username.fill('locked_out_user');
    await password.fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    // expect: Lockout error visible
    await expect(error).toHaveText('Epic sadface: Sorry, this user has been locked out.');

    // 2. Click [data-test="error-button"]
    await page.locator('[data-test="error-button"]').click();
    // expect: Error alert disappears, field error classes removed
    await expect(error).not.toBeVisible();
    await expect(username).not.toHaveClass(ERROR_CLASS);
    await expect(password).not.toHaveClass(ERROR_CLASS);

    // 3. Clear fields and fill with standard_user/secret_sauce, then submit
    await username.fill('standard_user');
    await password.fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    // expect: Login now succeeds and navigates to /inventory.html, confirming the dismissed error did not
    // leave the form in a broken state
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Error alert is not present on a freshly loaded login page', async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');

    // 1. Navigate to '/' in a brand-new context (no prior error triggered)
    // expect: [data-test="error"] element is not present/visible
    await expect(page.locator('[data-test="error"]')).not.toBeVisible();
    // expect: Neither field carries the 'error' CSS class
    // expect: This is the baseline negative check that the X button test relies on by contrast
    await expect(username).not.toHaveClass(ERROR_CLASS);
    await expect(password).not.toHaveClass(ERROR_CLASS);
  });
});
