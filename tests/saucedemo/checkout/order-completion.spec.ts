// spec: specs/saucedemo-checkout-test-plan.md
// seed: tests/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC4 - Order Completion', () => {
  test.beforeEach(async ({ page }) => {
    // Replicate seed login so every test starts logged in on /inventory.html
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);

    // Add 'Sauce Labs Backpack' to the cart and complete the checkout info form with valid data
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await page.locator('[data-test="checkout"]').click();
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="postalCode"]').fill('12345');
    await page.locator('[data-test="continue"]').click();
    await expect(page).toHaveURL(/checkout-step-two\.html/);
  });

  test('Clicking Finish completes the order, shows the confirmation message, and clears the cart', async ({ page }) => {
    // 2. Click 'Finish' (data-test=finish).
    await page.locator('[data-test="finish"]').click();

    // Page navigates to /checkout-complete.html
    await expect(page).toHaveURL(/checkout-complete\.html/);

    // complete-header is a real <h2> heading
    await expect(page.locator('[data-test="complete-header"]')).toHaveText('Thank you for your order!');
    await expect(page.locator('[data-test="complete-text"]')).toHaveText(
      'Your order has been dispatched, and will arrive just as fast as the pony can get there!'
    );
    await expect(page.locator('[data-test="pony-express"]')).toBeVisible();
    await expect(page.locator('[data-test="back-to-products"]')).toBeVisible();

    // 3. Check the header cart icon - shopping-cart-badge is absent entirely when cart is empty.
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);
  });

  test('Back Home button returns to the products page with an empty cart', async ({ page }) => {
    // 1. Complete a full checkout to reach /checkout-complete.html.
    await page.locator('[data-test="finish"]').click();
    await expect(page).toHaveURL(/checkout-complete\.html/);

    // 2. Click 'Back Home' (data-test=back-to-products).
    await page.locator('[data-test="back-to-products"]').click();

    // Page navigates to /inventory.html
    await expect(page).toHaveURL(/inventory\.html/);

    // Cart badge is absent, confirming the cart remains empty after order completion
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);
  });
});
