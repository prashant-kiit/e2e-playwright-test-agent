// spec: specs/saucedemo-checkout-test-plan.md
// seed: tests/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('UI Element Validation', () => {
  test.beforeEach(async ({ page }) => {
    // Replicate seed login so every test starts logged in on /inventory.html
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('All expected UI elements are present and correctly labeled across the checkout flow', async ({ page }) => {
    // 1. On /cart.html (with at least one item), inspect the page structure.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await expect(page).toHaveURL(/cart\.html/);

    // Column headers 'QTY' and 'Description' are visible
    await expect(page.locator('[data-test="cart-quantity-label"]')).toHaveText('QTY');
    await expect(page.locator('[data-test="cart-desc-label"]')).toHaveText('Description');

    // 'Continue Shopping' and 'Checkout' buttons are present with correct, clickable state
    await expect(page.locator('[data-test="continue-shopping"]')).toBeEnabled();
    await expect(page.locator('[data-test="checkout"]')).toBeEnabled();

    // 2. Navigate to /checkout-step-one.html.
    await page.locator('[data-test="checkout"]').click();
    await expect(page).toHaveURL(/checkout-step-one\.html/);

    // Page heading reads 'Checkout: Your Information'
    await expect(page.locator('[data-test="title"]')).toHaveText('Checkout: Your Information');

    // First Name, Last Name, and Zip/Postal Code inputs are present with correct placeholder text
    await expect(page.locator('[data-test="firstName"]')).toHaveAttribute('placeholder', 'First Name');
    await expect(page.locator('[data-test="lastName"]')).toHaveAttribute('placeholder', 'Last Name');
    await expect(page.locator('[data-test="postalCode"]')).toHaveAttribute('placeholder', 'Zip/Postal Code');

    // 'Cancel' and 'Continue' buttons are present and enabled
    await expect(page.locator('[data-test="cancel"]')).toBeEnabled();
    await expect(page.locator('[data-test="continue"]')).toBeEnabled();

    // 3. Complete the form and proceed to /checkout-step-two.html.
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="postalCode"]').fill('12345');
    await page.locator('[data-test="continue"]').click();
    await expect(page).toHaveURL(/checkout-step-two\.html/);

    // Page heading reads 'Checkout: Overview'
    await expect(page.locator('[data-test="title"]')).toHaveText('Checkout: Overview');

    // Payment Information and Shipping Information section labels are present
    await expect(page.locator('[data-test="payment-info-label"]')).toBeVisible();
    await expect(page.locator('[data-test="shipping-info-label"]')).toBeVisible();

    // Price Total section shows item total, tax, and total labels
    await expect(page.locator('[data-test="subtotal-label"]')).toBeVisible();
    await expect(page.locator('[data-test="tax-label"]')).toBeVisible();
    await expect(page.locator('[data-test="total-label"]')).toBeVisible();

    // 'Cancel' and 'Finish' buttons are present and enabled
    await expect(page.locator('[data-test="cancel"]')).toBeEnabled();
    await expect(page.locator('[data-test="finish"]')).toBeEnabled();

    // 4. Click 'Finish' to reach /checkout-complete.html.
    await page.locator('[data-test="finish"]').click();
    await expect(page).toHaveURL(/checkout-complete\.html/);

    // Confirmation header, body text, pony express image, and 'Back Home' button are all present and visible
    await expect(page.locator('[data-test="complete-header"]')).toBeVisible();
    await expect(page.locator('[data-test="complete-text"]')).toBeVisible();
    await expect(page.locator('[data-test="pony-express"]')).toBeVisible();
    await expect(page.locator('[data-test="back-to-products"]')).toBeVisible();
  });
});
