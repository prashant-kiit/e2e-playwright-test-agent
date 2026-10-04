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

  test('Cart displays correct item details, quantities, and supports navigation options', async ({ page }) => {
    // 1. Starting on /inventory.html (logged in), add 'Sauce Labs Backpack' and 'Sauce Labs Bike Light' to the cart using their Add to cart buttons.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="add-to-cart-sauce-labs-bike-light"]').click();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('2');

    // 2. Click the shopping cart link/icon in the header.
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page).toHaveURL(/cart\.html/);
    await expect(page.locator('[data-test="title"]')).toHaveText('Your Cart');

    // 3. Inspect the cart list rows.
    const backpackRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Backpack' });
    await expect(backpackRow.locator('[data-test="item-quantity"]')).toHaveText('1');
    await expect(backpackRow.locator('[data-test="inventory-item-desc"]')).toBeVisible();
    await expect(backpackRow.locator('[data-test="inventory-item-price"]')).toHaveText('$29.99');

    const bikeLightRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Bike Light' });
    await expect(bikeLightRow.locator('[data-test="item-quantity"]')).toHaveText('1');
    await expect(bikeLightRow.locator('[data-test="inventory-item-desc"]')).toBeVisible();
    await expect(bikeLightRow.locator('[data-test="inventory-item-price"]')).toHaveText('$9.99');

    await expect(page.locator('[data-test="continue-shopping"]')).toBeEnabled();
    await expect(page.locator('[data-test="checkout"]')).toBeEnabled();
  });

  test('Continue Shopping returns to products page and preserves cart contents', async ({ page }) => {
    // 1. Add 'Sauce Labs Backpack' to the cart from /inventory.html, then open the cart page.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page).toHaveURL(/cart\.html/);
    await expect(page.locator('[data-test="title"]')).toHaveText('Your Cart');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(1);
    const backpackRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Backpack' });
    await expect(backpackRow.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Backpack');

    // 2. Click 'Continue Shopping' (data-test=continue-shopping).
    await page.locator('[data-test="continue-shopping"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
  });

  test('Removing an item from the cart updates the list and badge count', async ({ page }) => {
    // 1. Add 'Sauce Labs Backpack' and 'Sauce Labs Bike Light' to the cart, then open /cart.html.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="add-to-cart-sauce-labs-bike-light"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(2);
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('2');

    // 2. Click 'Remove' (data-test=remove-sauce-labs-backpack) on the Backpack row.
    await page.locator('[data-test="remove-sauce-labs-backpack"]').click();
    await expect(page.locator('[data-test="remove-sauce-labs-backpack"]')).toHaveCount(0);
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(1);
    await expect(page.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Bike Light');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
  });

  test('Checkout button navigates to the Information step, and remains accessible with an empty cart', async ({ page }) => {
    // 1. With the cart empty, navigate to /cart.html.
    await page.goto('/cart.html');
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(0);
    await expect(page.locator('[data-test="checkout"]')).toBeVisible();
    await expect(page.locator('[data-test="checkout"]')).toBeEnabled();

    // 2. Click 'Checkout' (data-test=checkout).
    await page.locator('[data-test="checkout"]').click();
    await expect(page).toHaveURL(/checkout-step-one\.html/);
    await expect(page.locator('[data-test="title"]')).toHaveText('Checkout: Your Information');
  });
});
