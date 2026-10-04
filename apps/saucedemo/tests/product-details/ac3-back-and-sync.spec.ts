// spec: apps/saucedemo/specs/SCRUM-104-product-details-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC3 - Back to Products Navigation and State Sync', () => {
  test.beforeEach(async ({ page }) => {
    // Repeat the seed's login steps so each test starts from a fresh, independent session.
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Back to products returns to the catalog URL', async ({ page }) => {
    // id=3 is Test.allTheThings() T-Shirt (Red).
    await page.goto('/inventory-item.html?id=3');
    await expect(page.locator('[data-test="inventory-item-name"]')).toHaveText('Test.allTheThings() T-Shirt (Red)');

    await page.locator('[data-test="back-to-products"]').click();

    await expect(page).toHaveURL('/inventory.html');
    await expect(page.locator('.inventory_item')).toHaveCount(6);
  });

  test('Cart changes made on the detail page are reflected on the catalog after Back to products, and vice versa', async ({ page }) => {
    // Add the Backpack (id=4) to the cart from the detail page.
    await page.goto('/inventory-item.html?id=4');
    await page.locator('[data-test="add-to-cart"]').click();
    await expect(page.locator('[data-test="remove"]')).toBeVisible();

    await page.locator('[data-test="back-to-products"]').click();

    await expect(page).toHaveURL('/inventory.html');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toBeVisible();

    // Remove on the catalog, then reopen the detail page to confirm two-way sync.
    await page.locator('[data-test="remove-sauce-labs-backpack"]').click();
    await page.goto('/inventory-item.html?id=4');
    await expect(page.locator('[data-test="add-to-cart"]')).toBeVisible();
  });
});
