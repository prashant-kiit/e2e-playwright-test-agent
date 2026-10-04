// spec: apps/saucedemo/specs/SCRUM-102-login-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC1 - Successful Login', () => {
  test.beforeEach(async ({ page }) => {
    // 1. Navigate to '/' (fresh, logged-out context)
    await page.goto('/');
  });

  test('Standard user logs in successfully via Login button click', async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');
    const loginButton = page.locator('[data-test="login-button"]');

    // expect: Login page is displayed with empty Username and Password fields
    await expect(username).toBeEmpty();
    await expect(password).toBeEmpty();
    // expect: Login button [data-test="login-button"] is visible and enabled
    await expect(loginButton).toBeVisible();
    await expect(loginButton).toBeEnabled();

    // 2. Fill [data-test="username"] with 'standard_user'
    await username.fill('standard_user');
    // expect: Username field shows 'standard_user'
    await expect(username).toHaveValue('standard_user');

    // 3. Fill [data-test="password"] with 'secret_sauce'
    await password.fill('secret_sauce');
    // expect: Password field shows masked value (input type=password)
    await expect(password).toHaveAttribute('type', 'password');

    // 4. Click [data-test="login-button"]
    await loginButton.click();
    // expect: Browser navigates to /inventory.html
    await expect(page).toHaveURL(/inventory\.html/);
    // expect: The products page heading '.title' displays text 'Products'
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');
    // expect: No error alert ([data-test="error"]) is present
    await expect(page.locator('[data-test="error"]')).not.toBeVisible();
    // expect: At least one product card (e.g. 'Sauce Labs Backpack') is visible
    await expect(page.getByText('Sauce Labs Backpack')).toBeVisible();
  });

  test('Standard user logs in successfully by pressing Enter in the password field', async ({ page }) => {
    const username = page.locator('[data-test="username"]');
    const password = page.locator('[data-test="password"]');

    // expect: Login page is displayed
    await expect(page.locator('[data-test="login-button"]')).toBeVisible();

    // 2. Fill [data-test="username"] with 'standard_user'
    await username.fill('standard_user');
    // expect: Username field shows 'standard_user'
    await expect(username).toHaveValue('standard_user');

    // 3. Fill [data-test="password"] with 'secret_sauce' and press Enter (do not click the Login button)
    await password.fill('secret_sauce');
    await password.press('Enter');

    // expect: Form submits the same as a button click; Browser navigates to /inventory.html
    await expect(page).toHaveURL(/inventory\.html/);
    // expect: Page heading shows 'Products'
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');
  });

  test('Login page displays the accepted usernames list and shared password hint', async ({ page }) => {
    // 2. Read text content of [data-test="login-credentials"]
    const credentials = page.locator('[data-test="login-credentials"]');
    // expect: Text contains heading 'Accepted usernames are:' followed by: standard_user, locked_out_user, problem_user, performance_glitch_user, error_user, visual_user
    await expect(credentials).toContainText('Accepted usernames are:');
    await expect(credentials).toContainText('standard_user');
    await expect(credentials).toContainText('locked_out_user');
    await expect(credentials).toContainText('problem_user');
    await expect(credentials).toContainText('performance_glitch_user');
    await expect(credentials).toContainText('error_user');
    await expect(credentials).toContainText('visual_user');

    // 3. Read text content of [data-test="login-password"]
    const passwordHint = page.locator('[data-test="login-password"]');
    // expect: Text contains heading 'Password for all users:' followed by 'secret_sauce'
    await expect(passwordHint).toContainText('Password for all users:');
    await expect(passwordHint).toContainText('secret_sauce');
  });

  test('Each additional accepted username can log in with the shared password (data-driven)', async ({ page }) => {
    const otherUsers = ['problem_user', 'performance_glitch_user', 'error_user', 'visual_user'];

    // 1. For each username: navigate to '/' in a fresh context, fill username/password, click login
    for (const user of otherUsers) {
      await page.goto('/');
      await page.locator('[data-test="username"]').fill(user);
      await page.locator('[data-test="password"]').fill('secret_sauce');
      await page.locator('[data-test="login-button"]').click();

      // expect: For every username in the list, the browser navigates to /inventory.html
      await expect(page).toHaveURL(/inventory\.html/);
      // expect: No login error alert is shown
      await expect(page.locator('[data-test="error"]')).not.toBeVisible();
    }
  });

  test('Password field masks input characters', async ({ page }) => {
    const password = page.locator('[data-test="password"]');

    // 2. Fill [data-test="password"] with 'secret_sauce'
    await password.fill('secret_sauce');
    // expect: The input element's type attribute is 'password' so the value is visually masked (not plain text) in the UI
    await expect(password).toHaveAttribute('type', 'password');
    await expect(password).toHaveValue('secret_sauce');
  });
});
