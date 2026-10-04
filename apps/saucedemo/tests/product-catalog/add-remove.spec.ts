// spec: apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Add and Remove from List (AC4)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Adding a single product updates its button to Remove and increments the badge', async ({ page }) => {
    // 1. Start from the seed file. Assert [data-test="shopping-cart-badge"] is absent.
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);

    // 2. Click [data-test="add-to-cart-sauce-labs-backpack"].
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveText('Remove');

    // 3. Read [data-test="shopping-cart-badge"] text.
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
  });

  test('Removing a product reverts its button and decrements the badge to zero (badge disappears)', async ({ page }) => {
    // 1. Start from the seed file. Click [data-test="add-to-cart-sauce-labs-backpack"] to add the item first.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveText('Remove');

    // 2. Click [data-test="remove-sauce-labs-backpack"].
    await page.locator('[data-test="remove-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="add-to-cart-sauce-labs-backpack"]')).toHaveText('Add to cart');

    // 3. Query [data-test="shopping-cart-badge"].
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);
  });

  test('Adding multiple distinct products increments the badge cumulatively', async ({ page }) => {
    const badge = page.locator('[data-test="shopping-cart-badge"]');

    // 1. Start from the seed file.
    await expect(badge).toHaveCount(0);

    // 2. Click [data-test="add-to-cart-sauce-labs-backpack"].
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await expect(badge).toHaveText('1');

    // 3. Click [data-test="add-to-cart-sauce-labs-onesie"].
    await page.locator('[data-test="add-to-cart-sauce-labs-onesie"]').click();
    await expect(badge).toHaveText('2');

    // 4. Click [data-test="add-to-cart-sauce-labs-bike-light"].
    await page.locator('[data-test="add-to-cart-sauce-labs-bike-light"]').click();
    await expect(badge).toHaveText('3');

    // 5. Verify all three corresponding buttons now read 'Remove', while the other 3 unaffected products still show 'Add to cart'.
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveText('Remove');
    await expect(page.locator('[data-test="remove-sauce-labs-onesie"]')).toHaveText('Remove');
    await expect(page.locator('[data-test="remove-sauce-labs-bike-light"]')).toHaveText('Remove');
    await expect(page.locator('[data-test="add-to-cart-sauce-labs-bolt-t-shirt"]')).toHaveText('Add to cart');
    await expect(page.locator('[data-test="add-to-cart-sauce-labs-fleece-jacket"]')).toHaveText('Add to cart');
    await expect(page.locator('[data-test="add-to-cart-test.allthethings()-t-shirt-(red)"]')).toHaveText('Add to cart');

    // 6. Click remove-sauce-labs-onesie.
    await page.locator('[data-test="remove-sauce-labs-onesie"]').click();
    await expect(badge).toHaveText('2');
    await expect(page.locator('[data-test="add-to-cart-sauce-labs-onesie"]')).toHaveText('Add to cart');
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveText('Remove');
    await expect(page.locator('[data-test="remove-sauce-labs-bike-light"]')).toHaveText('Remove');
  });

  test('Add-to-cart button state for an item survives changing the sort order', async ({ page }) => {
    const sortDropdown = page.locator('[data-test="product-sort-container"]');
    const badge = page.locator('[data-test="shopping-cart-badge"]');

    // 1. Start from the seed file. Click [data-test="add-to-cart-sauce-labs-backpack"] to add Backpack to the cart.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveText('Remove');
    await expect(badge).toHaveText('1');

    // 2. Select 'hilo' (Price high to low) on [data-test="product-sort-container"].
    await sortDropdown.selectOption('hilo');
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Price (high to low)');

    // 3. Locate the Sauce Labs Backpack card again (now at a different position) and inspect its button.
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveText('Remove');
    await expect(badge).toHaveText('1');

    // 4. Select 'za' (Name Z to A) on the sort dropdown.
    await sortDropdown.selectOption('za');
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Name (Z to A)');

    // 5. Locate the Backpack card again.
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveText('Remove');
    await expect(badge).toHaveText('1');

    // 6. Click the Backpack's Remove button in this new sort position.
    await page.locator('[data-test="remove-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="add-to-cart-sauce-labs-backpack"]')).toHaveText('Add to cart');
    await expect(badge).toHaveCount(0);
  });
});
