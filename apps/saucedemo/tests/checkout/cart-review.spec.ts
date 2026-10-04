// spec: apps/saucedemo/specs/SCRUM-101-checkout-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC1 - Cart Review', () => {
  test.beforeEach(async ({ page }) => {
    // Replicate seed login so every test starts logged in on /inventory.html
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Cart displays single added item with name, description, price, quantity and action buttons', async ({ page }) => {
    // 1. Start on /inventory.html (seeded, logged in).
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(6);

    // 2. Click [data-test="add-to-cart-sauce-labs-backpack"].
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toBeVisible();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');

    // 3. Click [data-test="shopping-cart-link"].
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page).toHaveURL(/cart\.html/);
    await expect(page.locator('[data-test="title"]')).toHaveText('Your Cart');

    // 4. Inspect the cart row for Sauce Labs Backpack.
    const backpackRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Backpack' });
    await expect(backpackRow.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Backpack');
    await expect(backpackRow.locator('[data-test="inventory-item-desc"]')).toBeVisible();
    await expect(backpackRow.locator('[data-test="inventory-item-price"]')).toHaveText('$29.99');
    await expect(backpackRow.locator('[data-test="item-quantity"]')).toHaveText('1');

    // 5. Inspect page-level controls.
    await expect(page.locator('[data-test="continue-shopping"]')).toBeVisible();
    await expect(page.locator('[data-test="checkout"]')).toBeVisible();
    await expect(page.locator('[data-test="subtotal-label"]')).toHaveCount(0);
    await expect(page.locator('[data-test="total-label"]')).toHaveCount(0);
  });

  test('Cart displays multiple items each with correct name, description, price, quantity', async ({ page }) => {
    // 1. From /inventory.html, click [data-test="add-to-cart-sauce-labs-backpack"] then [data-test="add-to-cart-sauce-labs-bike-light"].
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="add-to-cart-sauce-labs-bike-light"]').click();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('2');

    // 2. Click [data-test="shopping-cart-link"] to open /cart.html.
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page).toHaveURL(/cart\.html/);
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(2);

    // 3. Verify row 1 (Sauce Labs Backpack) and row 2 (Sauce Labs Bike Light).
    const backpackRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Backpack' });
    await expect(backpackRow.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Backpack');
    await expect(backpackRow.locator('[data-test="inventory-item-desc"]')).toBeVisible();
    await expect(backpackRow.locator('[data-test="inventory-item-price"]')).toHaveText('$29.99');
    await expect(backpackRow.locator('[data-test="item-quantity"]')).toHaveText('1');

    const bikeLightRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Bike Light' });
    await expect(bikeLightRow.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Bike Light');
    await expect(bikeLightRow.locator('[data-test="inventory-item-desc"]')).toBeVisible();
    await expect(bikeLightRow.locator('[data-test="inventory-item-price"]')).toHaveText('$9.99');
    await expect(bikeLightRow.locator('[data-test="item-quantity"]')).toHaveText('1');

    // 4. Confirm [data-test="continue-shopping"] and [data-test="checkout"] are both present and enabled.
    await expect(page.locator('[data-test="continue-shopping"]')).toBeEnabled();
    await expect(page.locator('[data-test="checkout"]')).toBeEnabled();
  });

  test('Continue Shopping from cart returns to products page preserving cart contents', async ({ page }) => {
    // 1. Add Sauce Labs Backpack to cart, navigate to /cart.html via [data-test="shopping-cart-link"].
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page).toHaveURL(/cart\.html/);
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(1);

    // 2. Click [data-test="continue-shopping"].
    await page.locator('[data-test="continue-shopping"]').click();
    await expect(page).toHaveURL(/inventory\.html/);

    // 3. Click [data-test="shopping-cart-link"] again.
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page).toHaveURL(/cart\.html/);
    const backpackRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Backpack' });
    await expect(backpackRow).toHaveCount(1);
    await expect(backpackRow.locator('[data-test="item-quantity"]')).toHaveText('1');
  });

  test('Removing an item from the cart page updates the list and badge', async ({ page }) => {
    // 1. Add Sauce Labs Backpack and Sauce Labs Bike Light to cart; open /cart.html.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="add-to-cart-sauce-labs-bike-light"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(2);
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('2');

    // 2. Click [data-test="remove-sauce-labs-backpack"].
    await page.locator('[data-test="remove-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(1);
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');

    // 3. Remove the remaining item [data-test="remove-sauce-labs-bike-light"].
    await page.locator('[data-test="remove-sauce-labs-bike-light"]').click();
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(0);
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);
  });
});
