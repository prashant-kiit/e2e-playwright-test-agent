// spec: apps/saucedemo/specs/SCRUM-104-product-details-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC4 - Direct Link Access Control', () => {
  test.beforeEach(async ({ page }) => {
    // Repeat the seed's login steps so each test starts from a fresh, independent session.
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Direct navigation to a valid product id while logged in shows that product', async ({ page }) => {
    // id=5 is Sauce Labs Fleece Jacket.
    await page.goto('/inventory-item.html?id=5');
    await expect(page).toHaveURL('/inventory-item.html?id=5');
    await expect(page.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Fleece Jacket');
    await expect(page.locator('[data-test="inventory-item-price"]')).toHaveText('$49.99');

    // id=1 is Sauce Labs Bolt T-Shirt.
    await page.goto('/inventory-item.html?id=1');
    await expect(page).toHaveURL('/inventory-item.html?id=1');
    await expect(page.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Bolt T-Shirt');
    await expect(page.locator('[data-test="inventory-item-price"]')).toHaveText('$15.99');
  });

  test('Direct navigation to a product id while logged out redirects to login with protected-page error', async ({ page }) => {
    // Log out via the side menu to exercise the logged-out state despite the seeded login.
    await page.locator('#react-burger-menu-btn').click();
    await page.locator('[data-test="logout-sidebar-link"]').click();
    await expect(page).toHaveURL('/');

    const errorBanner = page.locator('[data-test="error"]');
    const expectedError = "Epic sadface: You can only access '/inventory-item.html' when you are logged in.";

    await page.goto('/inventory-item.html?id=4');
    await expect(page).toHaveURL('/');
    await expect(errorBanner).toHaveText(expectedError);

    // Same redirect and error occur regardless of which id was requested (auth guard fires before id lookup).
    await page.goto('/inventory-item.html?id=2');
    await expect(page).toHaveURL('/');
    await expect(errorBanner).toHaveText(expectedError);

    // Log back in so the app returns to a clean, empty-cart state for subsequent tests.
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });
});
