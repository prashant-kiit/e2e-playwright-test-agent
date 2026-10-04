// spec: apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('AC2 - Default Sort State', () => {
  test.beforeEach(async ({ page }) => {
    // Repeat the seed login flow (standard_user / secret_sauce) to land on the Products page.
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Sort dropdown defaults to Name (A to Z) and products are listed alphabetically on fresh load', async ({ page }) => {
    // 1. Read the selected value of the sort dropdown.
    const sortSelect = page.locator('[data-test="product-sort-container"]');
    await expect(sortSelect).toHaveValue('az');
    const selectedLabel = await sortSelect.locator('option:checked').textContent();
    expect(selectedLabel).toBe('Name (A to Z)');

    // 2. Read the text of active-option next to the dropdown.
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Name (A to Z)');

    // 3. Read the inventory-item-name text of all 6 products in DOM order into array A.
    const namesA = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    expect(namesA).toHaveLength(6);

    // 4. Create array B = an independently-sorted copy of A (locale-aware ascending compare).
    const namesB = [...namesA].sort((a, b) => a.localeCompare(b));

    // 5. Assert A deep-equals B.
    expect(namesA).toEqual(namesB);
  });
});
