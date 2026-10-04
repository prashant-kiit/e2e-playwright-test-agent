// spec: specs/saucedemo-checkout-test-plan.md
// seed: tests/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Navigation Flow - Cancel, Back, and End-to-End Happy Path', () => {
  test.beforeEach(async ({ page }) => {
    // Replicate seed login so every test starts logged in on /inventory.html
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Cancel on Checkout Information page returns to Cart and preserves items', async ({ page }) => {
    // 1. Add 'Sauce Labs Backpack' to the cart and navigate to /checkout-step-one.html.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await page.locator('[data-test="checkout"]').click();
    await expect(page).toHaveURL(/checkout-step-one\.html/);
    await expect(page.locator('[data-test="firstName"]')).toBeVisible();

    // 2. Click 'Cancel' (data-test=cancel).
    await page.locator('[data-test="cancel"]').click();

    // Page navigates back to /cart.html
    await expect(page).toHaveURL(/cart\.html/);

    // 'Sauce Labs Backpack' is still listed in the cart (no data loss)
    await expect(page.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Backpack');
  });

  test('Cancel on Order Overview page returns to Products and preserves cart contents', async ({ page }) => {
    // 1. Add 'Sauce Labs Backpack' to the cart, complete the checkout info form with valid data, and reach /checkout-step-two.html.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await page.locator('[data-test="checkout"]').click();
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="postalCode"]').fill('12345');
    await page.locator('[data-test="continue"]').click();
    await expect(page).toHaveURL(/checkout-step-two\.html/);
    await expect(page.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Backpack');

    // 2. Click 'Cancel' on the overview page.
    await page.locator('[data-test="cancel"]').click();

    // Page navigates to /inventory.html (not back to the info form)
    await expect(page).toHaveURL(/inventory\.html/);

    // Cart badge still shows '1', confirming the order was not submitted and the cart item is preserved
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('1');
  });
});
