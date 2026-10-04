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

  test('Negative: empty First Name blocks submission with a field-specific error', async ({ page }) => {
    // 1. Leave First Name empty, fill Last Name = 'Doe', Zip = '12345'.
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="postalCode"]').fill('12345');
    await expect(page.locator('[data-test="lastName"]')).toHaveValue('Doe');
    await expect(page.locator('[data-test="postalCode"]')).toHaveValue('12345');

    // 2. Click 'Continue'.
    await page.locator('[data-test="continue"]').click();

    // URL remains /checkout-step-one.html (submission blocked)
    await expect(page).toHaveURL(/checkout-step-one\.html/);
    await expect(page.locator('[data-test="error"]')).toHaveText('Error: First Name is required');
  });

  test('Negative: empty Last Name blocks submission with a field-specific error', async ({ page }) => {
    // 1. Fill First Name = 'John', leave Last Name empty, fill Zip = '12345'.
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="postalCode"]').fill('12345');
    await expect(page.locator('[data-test="firstName"]')).toHaveValue('John');
    await expect(page.locator('[data-test="postalCode"]')).toHaveValue('12345');

    // 2. Click 'Continue'.
    await page.locator('[data-test="continue"]').click();

    // URL remains /checkout-step-one.html
    await expect(page).toHaveURL(/checkout-step-one\.html/);
    await expect(page.locator('[data-test="error"]')).toHaveText('Error: Last Name is required');
  });

  test('Negative: empty Zip/Postal Code blocks submission with a field-specific error', async ({ page }) => {
    // 1. Fill First Name = 'John', Last Name = 'Doe', leave Zip/Postal Code empty.
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="lastName"]').fill('Doe');
    await expect(page.locator('[data-test="firstName"]')).toHaveValue('John');
    await expect(page.locator('[data-test="lastName"]')).toHaveValue('Doe');

    // 2. Click 'Continue'.
    await page.locator('[data-test="continue"]').click();

    // URL remains /checkout-step-one.html
    await expect(page).toHaveURL(/checkout-step-one\.html/);
    await expect(page.locator('[data-test="error"]')).toHaveText('Error: Postal Code is required');
  });

  test("Negative: all fields empty surfaces the first missing field's error", async ({ page }) => {
    // 1. Immediately click 'Continue' without entering any data.
    await page.locator('[data-test="continue"]').click();

    // URL remains /checkout-step-one.html
    await expect(page).toHaveURL(/checkout-step-one\.html/);

    // Error banner reads 'Error: First Name is required' (the first field in form order), not a generic or multi-field message
    await expect(page.locator('[data-test="error"]')).toHaveText('Error: First Name is required');
  });

  test('Error banner can be dismissed via the close (X) control', async ({ page }) => {
    // 1. Click 'Continue' with all fields empty to trigger the error banner.
    await page.locator('[data-test="continue"]').click();
    const errorBanner = page.locator('[data-test="error"]');
    await expect(errorBanner).toHaveText('Error: First Name is required');
    await expect(page.locator('[data-test="error-button"]')).toBeVisible();

    // 2. Click the dismiss (X) button on the error banner.
    await page.locator('[data-test="error-button"]').click();

    // The error banner is no longer visible, form fields remain editable and empty
    await expect(errorBanner).toHaveCount(0);
    const firstName = page.locator('[data-test="firstName"]');
    const lastName = page.locator('[data-test="lastName"]');
    const postalCode = page.locator('[data-test="postalCode"]');
    await expect(firstName).toBeEmpty();
    await expect(lastName).toBeEmpty();
    await expect(postalCode).toBeEmpty();
    await expect(firstName).toBeEditable();

    // 3. Fill all three fields with valid data and click Continue again.
    await firstName.fill('John');
    await lastName.fill('Doe');
    await postalCode.fill('12345');
    await page.locator('[data-test="continue"]').click();

    // Page proceeds to /checkout-step-two.html successfully
    await expect(page).toHaveURL(/checkout-step-two\.html/);
  });

  test('Sequential correction: fixing one invalid field at a time reveals the next required field error', async ({ page }) => {
    const errorBanner = page.locator('[data-test="error"]');

    // 1. With all fields empty, click Continue.
    await page.locator('[data-test="continue"]').click();
    await expect(errorBanner).toHaveText('Error: First Name is required');

    // 2. Fill First Name = 'John' only, click Continue again.
    await page.locator('[data-test="firstName"]').fill('John');
    await page.locator('[data-test="continue"]').click();
    await expect(errorBanner).toHaveText('Error: Last Name is required');

    // 3. Fill Last Name = 'Doe', leave Zip empty, click Continue again.
    await page.locator('[data-test="lastName"]').fill('Doe');
    await page.locator('[data-test="continue"]').click();
    await expect(errorBanner).toHaveText('Error: Postal Code is required');

    // 4. Fill Zip = '12345' and click Continue.
    await page.locator('[data-test="postalCode"]').fill('12345');
    await page.locator('[data-test="continue"]').click();

    // Page proceeds successfully to /checkout-step-two.html
    await expect(page).toHaveURL(/checkout-step-two\.html/);
  });
});
