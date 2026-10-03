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

  test('End-to-end happy path: Inventory to Cart to Info to Overview to Completion', async ({ page }) => {
    // 1. From /inventory.html, add 'Sauce Labs Backpack' and 'Sauce Labs Bike Light' to the cart.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="add-to-cart-sauce-labs-bike-light"]').click();
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveText('2');

    // 2. Open the cart via the cart icon.
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page).toHaveURL(/cart\.html/);
    const backpackRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Backpack' });
    const bikeLightRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Bike Light' });
    await expect(backpackRow.locator('[data-test="inventory-item-price"]')).toHaveText('$29.99');
    await expect(bikeLightRow.locator('[data-test="inventory-item-price"]')).toHaveText('$9.99');

    // 3. Click 'Checkout'.
    await page.locator('[data-test="checkout"]').click();
    await expect(page).toHaveURL(/checkout-step-one\.html/);

    // 4. Fill First Name = 'Jane', Last Name = 'Smith', Zip = '94107', then click 'Continue'.
    await page.locator('[data-test="firstName"]').fill('Jane');
    await page.locator('[data-test="lastName"]').fill('Smith');
    await page.locator('[data-test="postalCode"]').fill('94107');
    await page.locator('[data-test="continue"]').click();

    // Page navigates to /checkout-step-two.html showing both items, payment/shipping info, and correct totals
    await expect(page).toHaveURL(/checkout-step-two\.html/);
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(2);
    await expect(page.locator('[data-test="payment-info-value"]')).toHaveText('SauceCard #31337');
    await expect(page.locator('[data-test="shipping-info-value"]')).toHaveText('Free Pony Express Delivery!');
    await expect(page.locator('[data-test="subtotal-label"]')).toHaveText('Item total: $39.98');
    await expect(page.locator('[data-test="tax-label"]')).toHaveText('Tax: $3.20');
    await expect(page.locator('[data-test="total-label"]')).toHaveText('Total: $43.18');

    // 5. Click 'Finish'.
    await page.locator('[data-test="finish"]').click();

    // Page navigates to /checkout-complete.html with the 'Thank you for your order!' confirmation and cleared cart
    await expect(page).toHaveURL(/checkout-complete\.html/);
    await expect(page.locator('[data-test="complete-header"]')).toHaveText('Thank you for your order!');
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);

    // 6. Click 'Back Home'.
    await page.locator('[data-test="back-to-products"]').click();

    // Page returns to /inventory.html with an empty cart, ready for a new order
    await expect(page).toHaveURL(/inventory\.html/);
    await expect(page.locator('[data-test="shopping-cart-badge"]')).toHaveCount(0);
  });
});
