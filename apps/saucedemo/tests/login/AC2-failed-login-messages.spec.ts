// spec: apps/saucedemo/specs/SCRUM-102-login-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

// The 'input_error' CSS class token is always present on these inputs; a validation
// error adds an additional 'error' token (full className becomes "input_error form_input error").
// This regex asserts specifically on that 'error' token.
const ERROR_CLASS = /(^|\s)error(\s|$)/;

test.describe('AC2 - Failed Login Messages', () => {
  test.beforeEach(async ({ page }) => {
    // 1. Navigate to '/'
    await page.goto('/');
  });

  test("Submitting with both username and password empty shows 'Username is required'", async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');

    // 2. Click [data-test="login-button"] without filling any field
    await page.locator('[data-test="login-button"]').click();

    // expect: URL remains '/' (still on login page)
    await expect(page).toHaveURL('/');
    // expect: [data-test="error"] alert is visible with text exactly 'Epic sadface: Username is required'
    await expect(page.locator('[data-test="error"]')).toHaveText('Epic sadface: Username is required');
    // expect: [data-test="username"] and [data-test="password"] both carry the CSS class 'error'
    await expect(username).toHaveClass(ERROR_CLASS);
    await expect(password).toHaveClass(ERROR_CLASS);
  });

  test("Submitting with username filled and password empty shows 'Password is required'", async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');

    // 2. Fill [data-test="username"] with 'standard_user', leave password empty, click [data-test="login-button"]
    await username.fill('standard_user');
    await page.locator('[data-test="login-button"]').click();

    // expect: URL remains '/'
    await expect(page).toHaveURL('/');
    // expect: Error alert text is exactly 'Epic sadface: Password is required'
    await expect(page.locator('[data-test="error"]')).toHaveText('Epic sadface: Password is required');
    // expect: Username field retains 'standard_user'
    await expect(username).toHaveValue('standard_user');
    // expect: Both username and password fields carry the CSS class 'error'
    await expect(username).toHaveClass(ERROR_CLASS);
    await expect(password).toHaveClass(ERROR_CLASS);
  });

  test("Submitting with username empty and password filled still shows 'Username is required'", async ({ page }) => {
    const password = page.locator('[data-test="password"]');

    // 2. Leave username empty, fill [data-test="password"] with 'secret_sauce', click [data-test="login-button"]
    await password.fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();

    // expect: URL remains '/'
    await expect(page).toHaveURL('/');
    // expect: Error alert text is exactly 'Epic sadface: Username is required' (username validation takes precedence over password validation)
    await expect(page.locator('[data-test="error"]')).toHaveText('Epic sadface: Username is required');
    // expect: Password field retains the typed value
    await expect(password).toHaveValue('secret_sauce');
  });

  test('Wrong username and wrong password shows the generic mismatch error', async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');

    // 2. Fill username with 'invalid_user' and password with 'wrong_pass', submit via Enter key in the password field
    await username.fill('invalid_user');
    await password.fill('wrong_pass');
    await password.press('Enter');

    // expect: URL remains '/'
    await expect(page).toHaveURL('/');
    // expect: Error alert text is exactly 'Epic sadface: Username and password do not match any user in this service'
    await expect(page.locator('[data-test="error"]')).toHaveText(
      'Epic sadface: Username and password do not match any user in this service',
    );
    // expect: Both fields carry the CSS class 'error'
    await expect(username).toHaveClass(ERROR_CLASS);
    await expect(password).toHaveClass(ERROR_CLASS);
  });

  test('Valid username with wrong password shows the generic mismatch error', async ({ page }) => {
    // 2. Fill username with 'standard_user' and password with 'wrong_pass', click [data-test="login-button"]
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('wrong_pass');
    await page.locator('[data-test="login-button"]').click();

    // expect: URL remains '/'
    await expect(page).toHaveURL('/');
    // expect: Error text is exactly 'Epic sadface: Username and password do not match any user in this service'
    await expect(page.locator('[data-test="error"]')).toHaveText(
      'Epic sadface: Username and password do not match any user in this service',
    );
  });

  test('Wrong username with the correct shared password shows the generic mismatch error', async ({ page }) => {
    // 2. Fill username with 'not_a_real_user' and password with 'secret_sauce', click [data-test="login-button"]
    await page.locator('[data-test="username"]').fill('not_a_real_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();

    // expect: URL remains '/'
    await expect(page).toHaveURL('/');
    // expect: Error text is exactly 'Epic sadface: Username and password do not match any user in this service'
    await expect(page.locator('[data-test="error"]')).toHaveText(
      'Epic sadface: Username and password do not match any user in this service',
    );
  });

  test("Username match is case-sensitive - 'Standard_User' is rejected", async ({ page }) => {
    // 2. Fill username with 'Standard_User' (capitalized) and password with 'secret_sauce', submit
    await page.locator('[data-test="username"]').fill('Standard_User');
    const password = page.locator('[data-test="password"]');
    await password.fill('secret_sauce');
    await password.press('Enter');

    // expect: Login does NOT succeed; URL remains '/'
    await expect(page).toHaveURL('/');
    // expect: Error text is exactly 'Epic sadface: Username and password do not match any user in this service'
    // expect: Confirms username matching is case-sensitive
    await expect(page.locator('[data-test="error"]')).toHaveText(
      'Epic sadface: Username and password do not match any user in this service',
    );
  });

  test('Validation error highlights both username and password fields regardless of error type', async ({
    page,
  }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');
    const loginButton = page.locator('[data-test="login-button"]');

    // 1. Navigate to '/' and submit with empty username/password to trigger 'Username is required'
    await loginButton.click();
    // expect: Both fields className contains the token 'error' (in addition to the always-present 'input_error' token)
    await expect(username).toHaveClass(ERROR_CLASS);
    await expect(password).toHaveClass(ERROR_CLASS);

    // 2. Repeat for the wrong-credentials mismatch case
    await page.goto('/');
    await username.fill('not_a_real_user');
    await password.fill('wrong_pass');
    await loginButton.click();
    // expect: Both fields carry the 'error' class token
    await expect(username).toHaveClass(ERROR_CLASS);
    await expect(password).toHaveClass(ERROR_CLASS);

    // 2 (continued). Repeat for the locked_out_user case
    await page.goto('/');
    await username.fill('locked_out_user');
    await password.fill('secret_sauce');
    await loginButton.click();
    // expect: In every error scenario, both fields carry the 'error' class token, confirming consistent
    // field-level error marking across all AC2/AC3 error types
    await expect(username).toHaveClass(ERROR_CLASS);
    await expect(password).toHaveClass(ERROR_CLASS);
  });
});
