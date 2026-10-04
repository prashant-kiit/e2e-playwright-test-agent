// spec: apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

const EXPECTED_NAMES = [
  'Sauce Labs Backpack',
  'Sauce Labs Bike Light',
  'Sauce Labs Bolt T-Shirt',
  'Sauce Labs Fleece Jacket',
  'Sauce Labs Onesie',
  'Test.allTheThings() T-Shirt (Red)',
];

test.describe('AC3 - Sorting Options', () => {
  test.beforeEach(async ({ page }) => {
    // Repeat the seed login flow (standard_user / secret_sauce) to land on the Products page.
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Name (Z to A) sort reorders products in reverse alphabetical order and dropdown reflects selection', async ({ page }) => {
    // 1. Select option 'za' on the sort dropdown via a real control interaction (selectOption).
    const sortSelect = page.locator('[data-test="product-sort-container"]');
    await sortSelect.selectOption('za');
    await expect(sortSelect).toHaveValue('za');
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Name (Z to A)');

    // 2. Read inventory-item-name text of all 6 products in DOM order into array A.
    const namesA = await page.locator('[data-test="inventory-item-name"]').allTextContents();

    // 3. Create array B = an independently alphabetically-sorted copy of A, then reversed.
    const namesB = [...namesA].sort((a, b) => a.localeCompare(b)).reverse();

    // 4. Assert A deep-equals B.
    expect(namesA).toEqual(namesB);

    // 5. Assert the same 6 product names are present (as a set), with none added or removed.
    expect(new Set(namesA)).toEqual(new Set(EXPECTED_NAMES));
  });

  test('Price (low to high) sort reorders products by ascending price; equal-priced items may appear in either relative order', async ({ page }) => {
    // 1. Select option 'lohi' on the sort dropdown.
    const sortSelect = page.locator('[data-test="product-sort-container"]');
    await sortSelect.selectOption('lohi');
    await expect(sortSelect).toHaveValue('lohi');
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Price (low to high)');

    // 2. Read inventory-item-price (parsed as float) of all 6 products in DOM order into array P.
    const priceTexts = await page.locator('[data-test="inventory-item-price"]').allTextContents();
    const pricesP = priceTexts.map((t) => parseFloat(t.replace('$', '')));

    // 3. Create array Q = an independently, numerically ascending-sorted copy of P.
    const pricesQ = [...pricesP].sort((a, b) => a - b);

    // 4. Assert P deep-equals Q.
    expect(pricesP).toEqual(pricesQ);

    // 5. Assert the two $15.99 items (Bolt T-Shirt, Test.allTheThings) are adjacent, in either order.
    const namesInOrder = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    const idxBolt = namesInOrder.indexOf('Sauce Labs Bolt T-Shirt');
    const idxTest = namesInOrder.indexOf('Test.allTheThings() T-Shirt (Red)');
    expect(idxBolt).toBeGreaterThanOrEqual(0);
    expect(idxTest).toBeGreaterThanOrEqual(0);
    expect(Math.abs(idxBolt - idxTest)).toBe(1);
  });

  test('Price (high to low) sort reorders products by descending price; equal-priced items may appear in either relative order', async ({ page }) => {
    // 1. Select option 'hilo' on the sort dropdown.
    const sortSelect = page.locator('[data-test="product-sort-container"]');
    await sortSelect.selectOption('hilo');
    await expect(sortSelect).toHaveValue('hilo');
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Price (high to low)');

    // 2. Read inventory-item-price (parsed as float) of all 6 products in DOM order into array P.
    const priceTexts = await page.locator('[data-test="inventory-item-price"]').allTextContents();
    const pricesP = priceTexts.map((t) => parseFloat(t.replace('$', '')));

    // 3. Create array Q = an independently, numerically descending-sorted copy of P.
    const pricesQ = [...pricesP].sort((a, b) => b - a);

    // 4. Assert P deep-equals Q.
    expect(pricesP).toEqual(pricesQ);

    // 5. Assert the two $15.99 items are adjacent in the list regardless of mutual order.
    const namesInOrder = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    const idxBolt = namesInOrder.indexOf('Sauce Labs Bolt T-Shirt');
    const idxTest = namesInOrder.indexOf('Test.allTheThings() T-Shirt (Red)');
    expect(Math.abs(idxBolt - idxTest)).toBe(1);
  });

  test('Switching back to Name (A to Z) from another sort restores alphabetical order', async ({ page }) => {
    const sortSelect = page.locator('[data-test="product-sort-container"]');

    // 1. Starting from 'hilo' sort applied in a prior step, select option value 'az'.
    await sortSelect.selectOption('hilo');
    await expect(sortSelect).toHaveValue('hilo');

    await sortSelect.selectOption('az');
    await expect(sortSelect).toHaveValue('az');
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Name (A to Z)');

    // 2. Read inventory-item-name order into array A and compare against an independently sorted copy B.
    const namesA = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    const namesB = [...namesA].sort((a, b) => a.localeCompare(b));
    expect(namesA).toEqual(namesB);
  });

  test('Repeatedly cycling through all 4 sort options preserves the full set of 6 products each time (count/contents invariant)', async ({ page }) => {
    const sortSelect = page.locator('[data-test="product-sort-container"]');
    const baselineSet = new Set(EXPECTED_NAMES);
    const sequence = ['az', 'za', 'lohi', 'hilo', 'az'];

    // 1. In sequence, select each sort option, reading the full set of names after each selection.
    for (const value of sequence) {
      await sortSelect.selectOption(value);
      await expect(sortSelect).toHaveValue(value);

      const items = page.locator('[data-test="inventory-item"]');
      await expect(items).toHaveCount(6);

      const names = await page.locator('[data-test="inventory-item-name"]').allTextContents();
      expect(names).toHaveLength(6);
      expect(new Set(names)).toEqual(baselineSet);
    }
  });
});
