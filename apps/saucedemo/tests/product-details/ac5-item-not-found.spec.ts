// spec: apps/saucedemo/specs/SCRUM-104-product-details-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC5 - Unknown Product Handling', () => {
  test.beforeEach(async ({ page }) => {
    // Repeat the seed's login steps so each test starts from a fresh, independent session.
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Unknown product id=999 shows ITEM NOT FOUND content', async ({ page }) => {
    await page.goto('/inventory-item.html?id=999');

    await expect(page.locator('[data-test="inventory-item-name"]')).toHaveText('ITEM NOT FOUND');
    await expect(page.locator('[data-test="inventory-item-price"]')).toHaveText('$√-1');
    await expect(page.locator('.inventory_details_img')).toHaveAttribute('alt', 'ITEM NOT FOUND');
  });

  test('Back to products works from the ITEM NOT FOUND page', async ({ page }) => {
    await page.goto('/inventory-item.html?id=999');
    await expect(page.locator('[data-test="inventory-item-name"]')).toHaveText('ITEM NOT FOUND');

    await page.locator('[data-test="back-to-products"]').click();

    await expect(page).toHaveURL('/inventory.html');
    await expect(page.locator('.inventory_item')).toHaveCount(6);
  });
});
