// spec: specs/saucedemo/SCRUM-101-checkout-test-plan.md
// seed: tests/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC2 & AC5 - Checkout Information Entry and Validation', () => {
  test.beforeEach(async ({ page }) => {
    // Replicate seed login so every test starts logged in on /inventory.html
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Happy path: valid First Name, Last Name, and Zip proceed to Overview', async ({ page }) => {
    // 1. Add any product to the cart and navigate to /checkout-step-one.html.
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await page.locator('[data-test="checkout"]').click();
    await expect(page).toHaveURL(/checkout-step-one\.html/);

    const firstName = page.locator('[data-test="firstName"]');
    const lastName = page.locator('[data-test="lastName"]');
    const postalCode = page.locator('[data-test="postalCode"]');

    // Form shows empty First Name, Last Name, and Zip/Postal Code fields plus Cancel/Continue buttons
    await expect(firstName).toBeEmpty();
    await expect(lastName).toBeEmpty();
    await expect(postalCode).toBeEmpty();
    await expect(page.locator('[data-test="cancel"]')).toBeVisible();
    await expect(page.locator('[data-test="continue"]')).toBeVisible();

    // 2. Fill First Name = 'John', Last Name = 'Doe', Zip/Postal Code = '12345'.
    await firstName.fill('John');
    await lastName.fill('Doe');
    await postalCode.fill('12345');

    // Fields reflect the entered values, no error banner is shown
    await expect(firstName).toHaveValue('John');
    await expect(lastName).toHaveValue('Doe');
    await expect(postalCode).toHaveValue('12345');
    await expect(page.locator('[data-test="error"]')).toHaveCount(0);

    // 3. Click 'Continue' (data-test=continue).
    await page.locator('[data-test="continue"]').click();

    // Page navigates to /checkout-step-two.html ('Checkout: Overview') and no validation error is displayed
    await expect(page).toHaveURL(/checkout-step-two\.html/);
    await expect(page.locator('[data-test="title"]')).toHaveText('Checkout: Overview');
    await expect(page.locator('[data-test="error"]')).toHaveCount(0);
  });
});
