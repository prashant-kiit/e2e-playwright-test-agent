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

    // Add an item to the cart and navigate to /checkout-step-one.html via the cart page
    await page.locator('[data-test="add-to-cart-sauce-labs-backpack"]').click();
    await page.locator('[data-test="shopping-cart-link"]').click();
    await page.locator('[data-test="checkout"]').click();
    await expect(page).toHaveURL(/checkout-step-one\.html/);
  });

  test('Edge case: whitespace-only First Name is accepted (documents current validation gap)', async ({ page }) => {
    // 1. Fill First Name with only spaces ('   '), Last Name = 'Doe', Zip = '12345'.
    const firstName = page.locator('[data-test="firstName"]');
    await firstName.fill('   ');
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="postalCode"]').fill('12345');

    // Fields show the entered values
    await expect(firstName).toHaveValue('   ');
    await expect(page.locator('[data-test="lastName"]')).toHaveValue('Doe');
    await expect(page.locator('[data-test="postalCode"]')).toHaveValue('12345');

    // 2. Click 'Continue'.
    await page.locator('[data-test="continue"]').click();

    // Known validation gap: the app treats the whitespace value as non-empty and
    // navigates to /checkout-step-two.html without raising a 'required' error.
    await expect(page).toHaveURL(/checkout-step-two\.html/);
    await expect(page.locator('[data-test="error"]')).toHaveCount(0);
  });

  test('Edge case: special characters and long values are accepted in text fields', async ({ page }) => {
    const longLastName = 'a'.repeat(100);

    // 1. Fill First Name = "O'Brien-Test123", Last Name = a 100-character string, Zip = 'AB-123 456'.
    const firstName = page.locator('[data-test="firstName"]');
    const lastName = page.locator('[data-test="lastName"]');
    const postalCode = page.locator('[data-test="postalCode"]');
    await firstName.fill("O'Brien-Test123");
    await lastName.fill(longLastName);
    await postalCode.fill('AB-123 456');

    // Fields accept and display the entered values without truncation errors
    await expect(firstName).toHaveValue("O'Brien-Test123");
    await expect(lastName).toHaveValue(longLastName);
    await expect(postalCode).toHaveValue('AB-123 456');

    // 2. Click 'Continue'.
    await page.locator('[data-test="continue"]').click();

    // Page proceeds to /checkout-step-two.html (no client-side format validation blocks
    // special characters or long strings)
    await expect(page).toHaveURL(/checkout-step-two\.html/);
  });
});
