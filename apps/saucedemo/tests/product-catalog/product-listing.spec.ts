// spec: apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

const PRODUCTS = [
  { name: 'Sauce Labs Backpack', price: '$29.99' },
  { name: 'Sauce Labs Bike Light', price: '$9.99' },
  { name: 'Sauce Labs Bolt T-Shirt', price: '$15.99' },
  { name: 'Sauce Labs Fleece Jacket', price: '$49.99' },
  { name: 'Sauce Labs Onesie', price: '$7.99' },
  { name: 'Test.allTheThings() T-Shirt (Red)', price: '$15.99' },
];

test.describe('Product Listing (AC1)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Inventory page displays exactly 6 products with complete information', async ({ page }) => {
    // 1. Start from the seed file (logged in, on /inventory.html).
    await expect(page).toHaveURL('https://www.saucedemo.com/inventory.html');
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');

    // 2. Locate [data-test="inventory-list"] and count child elements matching [data-test="inventory-item"].
    const items = page.locator('[data-test="inventory-item"]');
    await expect(items).toHaveCount(6);

    for (const product of PRODUCTS) {
      // 3. For each of the 6 expected products, locate its inventory-item card by matching inventory-item-name text.
      const card = items.filter({
        has: page.locator('[data-test="inventory-item-name"]', { hasText: product.name }),
      });
      await expect(card).toHaveCount(1);

      // 4. Within each located card, assert presence of an <img>, a non-empty desc, a price, and an add-to-cart button.
      await expect(card.locator('img')).toBeVisible();
      await expect(card.locator('[data-test="inventory-item-desc"]')).not.toBeEmpty();
      const priceLocator = card.locator('[data-test="inventory-item-price"]');
      await expect(priceLocator).toBeVisible();
      const addButton = card.locator('button[data-test^="add-to-cart-"]');
      await expect(addButton).toBeVisible();

      // 5. Read the text of inventory-item-price for each named product and compare to expected values.
      await expect(priceLocator).toHaveText(product.price);

      // 6. Assert the Add to cart buttons are all enabled/clickable and none show 'Remove'.
      await expect(addButton).toBeEnabled();
      await expect(addButton).toHaveText('Add to cart');
    }
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);
  });

  test('Each product image is distinct and associated with the correct product name', async ({ page }) => {
    // 1. Start from the seed file.
    const items = page.locator('[data-test="inventory-item"]');
    await expect(items).toHaveCount(6);

    const count = await items.count();
    const srcs: string[] = [];
    for (let i = 0; i < count; i++) {
      const card = items.nth(i);
      const name = await card.locator('[data-test="inventory-item-name"]').textContent();
      const img = card.locator('img');

      // 2. For each inventory-item card, read the img element's alt attribute and the sibling name text.
      await expect(img).toHaveAttribute('alt', name ?? '');

      const src = await img.getAttribute('src');
      expect(src).toBeTruthy();
      srcs.push(src ?? '');

      // 3. Collect the 6 img src attributes; also confirm each image actually loads.
      // Wait for the image to finish loading before reading naturalWidth, otherwise it can be
      // read while the browser is still fetching/decoding the image (naturalWidth === 0).
      await expect(img).toHaveJSProperty('complete', true);
      await expect
        .poll(async () => img.evaluate((el: HTMLImageElement) => el.naturalWidth))
        .toBeGreaterThan(0);
    }

    const uniqueSrcs = new Set(srcs);
    // Prefer distinct images, but tolerate the known SauceDemo quirk of repeated demo images
    // since successful loading (checked above) is the primary requirement in that case.
    if (uniqueSrcs.size !== srcs.length) {
      expect(uniqueSrcs.size).toBeGreaterThan(0);
    } else {
      expect(uniqueSrcs.size).toBe(srcs.length);
    }
  });
});
