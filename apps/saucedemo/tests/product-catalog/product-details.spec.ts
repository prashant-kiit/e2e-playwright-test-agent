// spec: apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

const PRODUCTS = [
  { id: 0, name: 'Sauce Labs Bike Light' },
  { id: 1, name: 'Sauce Labs Bolt T-Shirt' },
  { id: 2, name: 'Sauce Labs Onesie' },
  { id: 3, name: 'Test.allTheThings() T-Shirt (Red)' },
  { id: 4, name: 'Sauce Labs Backpack' },
  { id: 5, name: 'Sauce Labs Fleece Jacket' },
];

test.describe('Links to Product Details (AC5)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test("Clicking a product name navigates to that product's detail page", async ({ page }) => {
    // 1. Start from the seed file, default az sort. Click [data-test="item-4-title-link"] (the Sauce Labs Backpack name).
    await page.locator('[data-test="item-4-title-link"]').click();
    await expect(page).toHaveURL('https://www.saucedemo.com/inventory-item.html?id=4');

    // 2. On the detail page, read the product name/price elements. Wait for the detail page's
    // unique "back-to-products" button first, since the list view can briefly still be in the
    // DOM right after the URL updates (SPA render transition), which would otherwise make the
    // inventory-item-name locator match the 6 list items instead of the single detail item.
    await expect(page.locator('[data-test="back-to-products"]')).toBeVisible();
    const detailName = page.locator('[data-test="inventory-item-name"]');
    await expect(detailName).toHaveCount(1);
    await expect(detailName).toHaveText('Sauce Labs Backpack');
    await expect(page.locator('[data-test="inventory-item-price"]')).toHaveText('$29.99');

    // 3. Click [data-test="back-to-products"].
    await page.locator('[data-test="back-to-products"]').click();
    await expect(page).toHaveURL('https://www.saucedemo.com/inventory.html');
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(6);
  });

  test("Clicking a product image navigates to that product's detail page", async ({ page }) => {
    // 1. Start from the seed file. Click [data-test="item-0-img-link"] (the Sauce Labs Bike Light image).
    await page.locator('[data-test="item-0-img-link"]').click();
    await expect(page).toHaveURL('https://www.saucedemo.com/inventory-item.html?id=0');

    // 2. On the detail page, read the product name/price elements. Wait for the detail page's
    // unique "back-to-products" button first to avoid racing the SPA render transition where the
    // list view's 6 inventory-item-name elements can still be present momentarily.
    await expect(page.locator('[data-test="back-to-products"]')).toBeVisible();
    const detailName = page.locator('[data-test="inventory-item-name"]');
    await expect(detailName).toHaveCount(1);
    await expect(detailName).toHaveText('Sauce Labs Bike Light');
    await expect(page.locator('[data-test="inventory-item-price"]')).toHaveText('$9.99');

    // 3. Click [data-test="back-to-products"] to return.
    await page.locator('[data-test="back-to-products"]').click();
    await expect(page).toHaveURL('https://www.saucedemo.com/inventory.html');
  });

  test("Each of the 6 products' name and image links both resolve to the same, correct detail id", async ({ page }) => {
    // 1. For each of the 6 known (slug/id) pairs, click [data-test="item-<id>-title-link"], capture the resulting URL, then navigate back via [data-test="back-to-products"].
    for (const product of PRODUCTS) {
      await page.locator(`[data-test="item-${product.id}-title-link"]`).click();
      await expect(page).toHaveURL(`https://www.saucedemo.com/inventory-item.html?id=${product.id}`);
      // Wait for the detail page's unique "back-to-products" button so the SPA render
      // transition has settled before reading the (now singular) inventory-item-name.
      const backButton = page.locator('[data-test="back-to-products"]');
      await expect(backButton).toBeVisible();
      const detailName = page.locator('[data-test="inventory-item-name"]');
      await expect(detailName).toHaveCount(1);
      await expect(detailName).toHaveText(product.name);
      await backButton.click();
      await expect(page).toHaveURL('https://www.saucedemo.com/inventory.html');
    }

    // 2. Repeat the same loop but clicking [data-test="item-<id>-img-link"] instead of the title link for each product.
    for (const product of PRODUCTS) {
      await page.locator(`[data-test="item-${product.id}-img-link"]`).click();
      await expect(page).toHaveURL(`https://www.saucedemo.com/inventory-item.html?id=${product.id}`);
      const backButton = page.locator('[data-test="back-to-products"]');
      await expect(backButton).toBeVisible();
      const detailName = page.locator('[data-test="inventory-item-name"]');
      await expect(detailName).toHaveCount(1);
      await expect(detailName).toHaveText(product.name);
      await backButton.click();
      await expect(page).toHaveURL('https://www.saucedemo.com/inventory.html');
    }
  });

  test('Add to cart from the detail page reflects back on the inventory list', async ({ page }) => {
    // 1. Click [data-test="item-4-title-link"] to open the Sauce Labs Backpack detail page.
    await page.locator('[data-test="item-4-title-link"]').click();
    await expect(page).toHaveURL('https://www.saucedemo.com/inventory-item.html?id=4');

    // 2. Click the detail page's [data-test="add-to-cart"] button.
    await page.locator('[data-test="add-to-cart"]').click();
    await expect(page.locator('[data-test="remove"]')).toHaveText('Remove');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');

    // 3. Click [data-test="back-to-products"] to return to the list.
    await page.locator('[data-test="back-to-products"]').click();
    await expect(page).toHaveURL('https://www.saucedemo.com/inventory.html');

    // 4. Locate the Sauce Labs Backpack card.
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveText('Remove');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
  });
});
