// spec: apps/saucedemo/specs/SCRUM-102-login-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC5 - Protected Pages and Logout', () => {
  test.beforeEach(async ({ page }) => {
    // Start every test from a fresh, logged-out context.
    await page.goto('/');
  });

  test('Direct navigation to a protected page while logged out redirects to login with the correct error', async ({
    page,
  }) => {
    // 1. In a fresh, logged-out context, navigate directly to '/inventory.html'
    await page.goto('/inventory.html');

    // expect: Browser URL is redirected to '/'
    await expect(page).toHaveURL('/');
    // expect: [data-test="error"] alert text is exactly "Epic sadface: You can only access '/inventory.html' when you are logged in."
    await expect(page.locator('[data-test="error"]')).toHaveText(
      "Epic sadface: You can only access '/inventory.html' when you are logged in.",
    );
    // expect: No product grid/content is rendered - only the login form is visible
    await expect(page.locator('[data-test="login-button"]')).toBeVisible();
    await expect(page.locator('.inventory_list')).toHaveCount(0);
  });

  test('Authenticated user can access the inventory page and sees the product catalog', async ({ page }) => {
    // 1. Navigate to '/', log in with standard_user/secret_sauce
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();

    // expect: Navigated to /inventory.html
    await expect(page).toHaveURL(/inventory\.html/);
    // expect: Page heading '.title' shows 'Products'
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');
    // expect: Product cards are rendered (e.g. 'Sauce Labs Backpack' visible)
    await expect(page.getByText('Sauce Labs Backpack')).toBeVisible();
  });

  test('Logout via the side menu returns the user to the login page', async ({ page }) => {
    // 1. Navigate to '/', log in with standard_user/secret_sauce to reach /inventory.html
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    // expect: On inventory page
    await expect(page).toHaveURL(/inventory\.html/);

    // 2. Open the side menu using page.getByRole('button', { name: 'Open Menu' })
    // (do NOT click [data-test="open-menu"] directly - it is covered by the visual button and will time out)
    await page.getByRole('button', { name: 'Open Menu' }).click();
    // expect: Side menu panel opens showing 'All Items', 'Dynamic Catalog', 'About', 'Logout', 'Reset App State'
    await expect(page.locator('[data-test="logout-sidebar-link"]')).toBeVisible();

    // 3. Click [data-test="logout-sidebar-link"] (the 'Logout' link)
    await page.locator('[data-test="logout-sidebar-link"]').click();

    // expect: Browser navigates back to '/'
    await expect(page).toHaveURL('/');
    // expect: A blank login form is displayed (no error alert)
    await expect(page.locator('[data-test="username"]')).toBeEmpty();
    await expect(page.locator('[data-test="error"]')).not.toBeVisible();
    // expect: No session/cart state is visible
    await expect(page.locator('[data-test="login-button"]')).toBeVisible();
  });

  test('Browser Back button after logout does not restore the protected product page', async ({ page }) => {
    // 1. Navigate to '/', log in with standard_user/secret_sauce to reach /inventory.html
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    // expect: On inventory page, Products heading visible
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');

    // 2. Open the side menu (getByRole button 'Open Menu') and click [data-test="logout-sidebar-link"] to log out
    await page.getByRole('button', { name: 'Open Menu' }).click();
    await page.locator('[data-test="logout-sidebar-link"]').click();
    // expect: Back on '/' with blank login form
    await expect(page).toHaveURL('/');

    // 3. Press the browser Back button (page.goBack())
    await page.goBack();

    // expect: The product catalog is NOT shown (no cached authenticated page is served from history)
    // expect: Browser ends up on '/' displaying the protected-page error - this is the key regression
    // check for this story: logout must truly invalidate the session, not just visually return to login
    // while leaving /inventory.html cached/accessible via history
    await expect(page).toHaveURL('/');
    await expect(page.locator('[data-test="error"]')).toHaveText(
      "Epic sadface: You can only access '/inventory.html' when you are logged in.",
    );
    await expect(page.locator('.inventory_list')).toHaveCount(0);
  });

  test('Side menu Open/Close controls work correctly around the logout action', async ({ page }) => {
    // 1. Navigate to '/', log in with standard_user/secret_sauce
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    // expect: On inventory page
    await expect(page).toHaveURL(/inventory\.html/);

    // 2. Click getByRole('button', { name: 'Open Menu' })
    await page.getByRole('button', { name: 'Open Menu' }).click();
    // expect: Menu panel becomes visible with 'Logout' link visible and not aria-hidden
    await expect(page.locator('[data-test="logout-sidebar-link"]')).toBeVisible();

    // 3. Click getByRole('button', { name: 'Close Menu' }) without logging out
    await page.getByRole('button', { name: 'Close Menu' }).click();
    // expect: Menu panel closes; product grid remains visible and the user is still logged in
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');

    // 4. Re-open the menu and click [data-test="logout-sidebar-link"]
    await page.getByRole('button', { name: 'Open Menu' }).click();
    // expect (re-opening the menu still shows Logout, confirming session persisted through an open/close cycle)
    await expect(page.locator('[data-test="logout-sidebar-link"]')).toBeVisible();
    await page.locator('[data-test="logout-sidebar-link"]').click();

    // expect: User is logged out and returned to '/'
    await expect(page).toHaveURL('/');
    await expect(page.locator('[data-test="login-button"]')).toBeVisible();
  });

  test("Directly re-navigating to '/inventory.html' immediately after logout still shows the protected-page error", async ({
    page,
  }) => {
    // 1. Navigate to '/', log in with standard_user/secret_sauce, then log out via the side menu
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);

    await page.getByRole('button', { name: 'Open Menu' }).click();
    await page.locator('[data-test="logout-sidebar-link"]').click();
    // expect: Back on '/' login form
    await expect(page).toHaveURL('/');

    // 2. Navigate directly (page.goto) to '/inventory.html' again
    await page.goto('/inventory.html');

    // expect: Redirected to '/'
    await expect(page).toHaveURL('/');
    // expect: Error alert exactly "Epic sadface: You can only access '/inventory.html' when you are logged in."
    // is shown, confirming no residual session/cookie allows access post-logout
    await expect(page.locator('[data-test="error"]')).toHaveText(
      "Epic sadface: You can only access '/inventory.html' when you are logged in.",
    );
  });
});
