// spec: apps/saucedemo/specs/SCRUM-101-checkout-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC3 - Order Overview', () => {
  test.beforeEach(async ({ page }) => {
    // Replicate seed login so every test starts logged in on /inventory.html
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Overview page shows item summary, payment/shipping info, and correct subtotal/tax/total', async ({ page }) => {
    // 1. Add 'Sauce Labs Backpack' ($29.99) to the cart, go to checkout info, fill valid data, and click Continue.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await page.locator('[data-test="checkout"]').click();
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="postalCode"]').fill('12345');
    await page.locator('[data-test="continue"]').click();

    await expect(page).toHaveURL(/checkout-step-two\.html/);
    await expect(page.locator('[data-test="title"]')).toHaveText('Checkout: Overview');

    // 2. Inspect the item summary section.
    const row = page.locator('[data-test="inventory-item"]');
    await expect(row.locator('[data-test="item-quantity"]')).toHaveText('1');
    await expect(row.locator('[data-test="inventory-item-name"]')).toHaveText('Sauce Labs Backpack');
    await expect(row.locator('[data-test="inventory-item-desc"]')).toBeVisible();
    await expect(row.locator('[data-test="inventory-item-price"]')).toHaveText('$29.99');

    // 3. Inspect the Payment Information and Shipping Information sections.
    await expect(page.locator('[data-test="payment-info-value"]')).toHaveText('SauceCard #31337');
    await expect(page.locator('[data-test="shipping-info-value"]')).toHaveText('Free Pony Express Delivery!');

    // 4. Inspect the Price Total section.
    await expect(page.locator('[data-test="subtotal-label"]')).toHaveText('Item total: $29.99');
    await expect(page.locator('[data-test="tax-label"]')).toHaveText('Tax: $2.40');
    await expect(page.locator('[data-test="total-label"]')).toHaveText('Total: $32.39');
    await expect(page.locator('[data-test="cancel"]')).toBeEnabled();
    await expect(page.locator('[data-test="finish"]')).toBeEnabled();
  });

  test('Overview totals correctly aggregate multiple cart items', async ({ page }) => {
    // 1. Add 'Sauce Labs Backpack' ($29.99) and 'Sauce Labs Bike Light' ($9.99) to the cart and proceed through checkout info.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="add-to-cart-sauce-labs-bike-light"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await page.locator('[data-test="checkout"]').click();
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="postalCode"]').fill('12345');
    await page.locator('[data-test="continue"]').click();
    await expect(page).toHaveURL(/checkout-step-two\.html/);

    // Both items are listed in the overview with correct individual prices
    const backpackRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Backpack' });
    const bikeLightRow = page.locator('[data-test="inventory-item"]').filter({ hasText: 'Sauce Labs Bike Light' });
    await expect(backpackRow.locator('[data-test="inventory-item-price"]')).toHaveText('$29.99');
    await expect(bikeLightRow.locator('[data-test="inventory-item-price"]')).toHaveText('$9.99');

    // 2. Inspect the Item total line.
    await expect(page.locator('[data-test="subtotal-label"]')).toHaveText('Item total: $39.98');

    // 3. Inspect the Tax and Total lines (Tax is 8% of item total; Total = Item total + Tax).
    await expect(page.locator('[data-test="tax-label"]')).toHaveText('Tax: $3.20');
    await expect(page.locator('[data-test="total-label"]')).toHaveText('Total: $43.18');
  });

  test('Edge case: Overview with an empty cart shows zeroed totals', async ({ page }) => {
    // 1. With the cart empty, navigate directly to /checkout-step-one.html, fill valid data, and click Continue.
    await page.goto('/checkout-step-one.html');
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="postalCode"]').fill('12345');
    await page.locator('[data-test="continue"]').click();

    // Page proceeds to /checkout-step-two.html despite no items in cart
    await expect(page).toHaveURL(/checkout-step-two\.html/);

    // 2. Inspect the item list and totals.
    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(0);
    await expect(page.locator('[data-test="subtotal-label"]')).toHaveText('Item total: $0');
    await expect(page.locator('[data-test="total-label"]')).toHaveText('Total: $0.00');
    await expect(page.locator('[data-test="finish"]')).toBeEnabled();
  });
});
