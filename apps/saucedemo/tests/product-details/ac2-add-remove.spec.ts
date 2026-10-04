// spec: apps/saucedemo/specs/SCRUM-104-product-details-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC2 - Add/Remove From Cart on Detail Page', () => {
  test.beforeEach(async ({ page }) => {
    // Repeat the seed's login steps so each test starts from a fresh, independent session
    // (a fresh browser context per test keeps cart state from leaking between tests).
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Add to cart from detail page updates button label and cart badge', async ({ page }) => {
    // Navigate to the Backpack (id=4) detail page and confirm starting state.
    await page.goto('/inventory-item.html?id=4');
    await expect(page.locator('[data-test="add-to-cart"]')).toHaveText('Add to cart');
    const cartIcon = page.locator('[data-test="shopping-cart-link"]');
    await expect(cartIcon).toHaveAttribute('aria-label', 'Cart, empty');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);

    await page.locator('[data-test="add-to-cart"]').click();

    await expect(page.locator('[data-test="remove"]')).toHaveText('Remove');
    await expect(cartIcon).toHaveAttribute('aria-label', 'Cart, 1 items');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
  });

  test('Remove from detail page reverts button label and decrements cart badge', async ({ page }) => {
    // Add the Backpack (id=4) to the cart first.
    await page.goto('/inventory-item.html?id=4');
    await page.locator('[data-test="add-to-cart"]').click();
    await expect(page.locator('[data-test="remove"]')).toHaveText('Remove');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');

    await page.locator('[data-test="remove"]').click();

    await expect(page.locator('[data-test="add-to-cart"]')).toHaveText('Add to cart');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);
    await expect(page.locator('[data-test="shopping-cart-link"]')).toHaveAttribute('aria-label', 'Cart, empty');
  });

  test('Adding multiple different products increments the badge cumulatively across detail-page visits', async ({ page }) => {
    // id=0 is Bike Light (ids are not in catalog order).
    await page.goto('/inventory-item.html?id=0');
    await page.locator('[data-test="add-to-cart"]').click();
    await expect(page.locator('[data-test="remove"]')).toBeVisible();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');

    // id=1 is Bolt T-Shirt. Badge must accumulate across navigation, not reset.
    await page.goto('/inventory-item.html?id=1');
    await page.locator('[data-test="add-to-cart"]').click();
    await expect(page.locator('[data-test="remove"]')).toBeVisible();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('2');

    // id=5 is Fleece Jacket, never added, confirming per-product state is independent.
    await page.goto('/inventory-item.html?id=5');
    await expect(page.locator('[data-test="add-to-cart"]')).toBeVisible();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('2');
  });

  test('A product added from the catalog shows Remove on its detail page, and removing on detail reflects back on the catalog', async ({ page }) => {
    // Add the Backpack from the catalog tile (catalog uses slug-based data-test ids).
    await page.goto('/inventory.html');
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toBeVisible();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');

    // Open the Backpack's detail page (id=4) directly and confirm the cart state carried over.
    await page.goto('/inventory-item.html?id=4');
    await expect(page.locator('[data-test="remove"]')).toBeVisible();

    await page.locator('[data-test="remove"]').click();
    await expect(page.locator('[data-test="add-to-cart"]')).toBeVisible();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);

    // Removing on the detail page must reflect back on the catalog tile.
    await page.goto('/inventory.html');
    await expect(page.locator('[data-test="add-to-cart-sauce-labs-backpack"]')).toBeVisible();
  });
});
