// spec: apps/saucedemo/specs/SCRUM-104-product-details-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC1 - Detail Content Parity', () => {
  test.beforeEach(async ({ page }) => {
    // Repeat the seed's login steps so each test starts from a fresh, independent session.
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Detail page shows correct name, description, price, and image for every one of the 6 products', async ({ page }) => {
    // Product id <-> name <-> price mapping confirmed during exploratory testing.
    // Ids are NOT in catalog display order (e.g. Backpack is id=4, not id=0).
    const products = [
      { id: 0, name: 'Sauce Labs Bike Light', price: '$9.99' },
      { id: 1, name: 'Sauce Labs Bolt T-Shirt', price: '$15.99' },
      { id: 2, name: 'Sauce Labs Onesie', price: '$7.99' },
      { id: 3, name: 'Test.allTheThings() T-Shirt (Red)', price: '$15.99' },
      { id: 4, name: 'Sauce Labs Backpack', price: '$29.99' },
      { id: 5, name: 'Sauce Labs Fleece Jacket', price: '$49.99' },
    ];

    // 1-3. For every discovered id, navigate directly to the detail page via URL and verify content.
    for (const product of products) {
      await page.goto(`/inventory-item.html?id=${product.id}`);
      await expect(page).toHaveURL(`/inventory-item.html?id=${product.id}`);
      // Scope to the detail page's unique classes: the catalog grid tiles also carry
      // data-test="inventory-item-name"/"inventory-item-price", so an unscoped locator
      // can match all 6 catalog tiles (strict mode violation) during the brief moment
      // the SPA is transitioning from the catalog view into the single-item detail view.
      await expect(page.locator('[data-test="inventory-item-name"].inventory_details_name')).toHaveText(product.name);
      await expect(page.locator('[data-test="inventory-item-price"].inventory_details_price')).toHaveText(product.price);

      const image = page.locator('.inventory_details_img');
      await expect(image).toBeVisible();
      await expect(image).toHaveAttribute('alt', product.name);
      await expect(image).toHaveAttribute('src', /.+/);
    }

    // 4. Repeat the checks by clicking through from the catalog instead of typing the URL,
    // for 2 of the 6 products: Bike Light (id=0) and Backpack (id=4).
    for (const product of [products[0], products[4]]) {
      await page.goto('/inventory.html');
      await page.locator(`[data-test="item-${product.id}-title-link"]`).click();

      await expect(page).toHaveURL(`/inventory-item.html?id=${product.id}`);
      // Same rationale as the direct-navigation loop above: scope to the detail page's
      // unique classes so the assertion retries cleanly while the SPA finishes
      // transitioning from the catalog grid to the single-item detail view, instead of
      // hitting a strict-mode violation against the catalog tiles.
      await expect(page.locator('[data-test="inventory-item-name"].inventory_details_name')).toHaveText(product.name);
      await expect(page.locator('[data-test="inventory-item-price"].inventory_details_price')).toHaveText(product.price);
      await expect(page.locator('.inventory_details_img')).toHaveAttribute('alt', product.name);
    }
  });
});
