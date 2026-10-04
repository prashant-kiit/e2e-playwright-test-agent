// spec: apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Default Sort (AC2)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Dropdown defaults to Name (A to Z) and list is alphabetically sorted on load', async ({ page }) => {
    // 1. Start from the seed file, freshly on /inventory.html without touching the sort dropdown.
    await expect(page).toHaveURL('https://www.saucedemo.com/inventory.html');

    // 2. Read the selected option's visible text from the sort dropdown.
    const sortDropdown = page.locator('[data-test="product-sort-container"]');
    await expect(sortDropdown).toHaveValue('az');
    await expect(sortDropdown.locator('option:checked')).toHaveText('Name (A to Z)');

    // 3. Read [data-test="active-option"] text.
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Name (A to Z)');

    // 4. Read all 6 inventory-item-name texts in DOM order into an array.
    const names = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    expect(names).toEqual([
      'Sauce Labs Backpack',
      'Sauce Labs Bike Light',
      'Sauce Labs Bolt T-Shirt',
      'Sauce Labs Fleece Jacket',
      'Sauce Labs Onesie',
      'Test.allTheThings() T-Shirt (Red)',
    ]);

    // 5. Independently verify by sorting a copy of the captured name array alphabetically and diffing against the captured order.
    const sortedNames = [...names].sort((a, b) => a.localeCompare(b));
    expect(names).toEqual(sortedNames);
  });
});
