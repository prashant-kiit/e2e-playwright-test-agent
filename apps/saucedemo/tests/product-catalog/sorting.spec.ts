// spec: apps/saucedemo/specs/SCRUM-103-product-catalog-test-plan.md
// seed: apps/saucedemo/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Sorting Options (AC3)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Sort dropdown exposes all four expected options with correct values and labels', async ({ page }) => {
    // 1. Start from the seed file.
    await expect(page).toHaveURL(/inventory\.html/);

    // 2. Query all <option> elements inside the sort dropdown and capture their value and text.
    const options = page.locator('[data-test="product-sort-container"] option');
    await expect(options).toHaveCount(4);
    const values = await options.evaluateAll((opts) => opts.map((o) => (o as HTMLOptionElement).value));
    const texts = await options.allTextContents();
    expect(values).toEqual(['az', 'za', 'lohi', 'hilo']);
    expect(texts).toEqual([
      'Name (A to Z)',
      'Name (Z to A)',
      'Price (low to high)',
      'Price (high to low)',
    ]);
  });

  test('Selecting Name (Z to A) reorders products reverse-alphabetically', async ({ page }) => {
    const nameLocator = page.locator('[data-test="inventory-item-name"]');

    // 1. Start from the seed file. Capture the current list of 6 product names before sorting.
    // Wait for all 6 cards to be rendered first: right after the beforeEach's URL check, the
    // inventory grid can still be mid-render, so reading names immediately can yield an empty
    // (or partial) array.
    await expect(nameLocator).toHaveCount(6);
    const baseline = await nameLocator.allTextContents();

    // 2. Use selectOption on the sort dropdown with value 'za'.
    await page.locator('[data-test="product-sort-container"]').selectOption('za');

    // 3. Read [data-test="active-option"] text.
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Name (Z to A)');

    // 4. Read the 6 product names in DOM order after sorting.
    const afterSort = await nameLocator.allTextContents();

    // 5. Programmatically sort a copy of the baseline names descending and compare to the captured post-sort order.
    const expectedDescending = [...baseline].sort((a, b) => b.localeCompare(a));
    expect(afterSort).toEqual(expectedDescending);
    expect(afterSort).toEqual([...baseline].reverse());
  });

  test('Selecting Price (low to high) reorders products by ascending price', async ({ page }) => {
    // 1. Start from the seed file, default az sort.
    await expect(page.locator('[data-test="product-sort-container"]')).toHaveValue('az');

    // 2. Use selectOption on the sort dropdown with value 'lohi'.
    await page.locator('[data-test="product-sort-container"]').selectOption('lohi');

    // 3. Read [data-test="active-option"] text.
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Price (low to high)');

    // 4. Parse the inventory-item-price text for all 6 cards in DOM order.
    const priceTexts = await page.locator('[data-test="inventory-item-price"]').allTextContents();
    const prices = priceTexts.map((p) => parseFloat(p.replace('$', '')));
    expect(prices).toEqual([7.99, 9.99, 15.99, 15.99, 29.99, 49.99]);

    // 5. Assert programmatically that the captured price array is non-decreasing.
    expect(prices.every((p, i) => i === prices.length - 1 || p <= prices[i + 1])).toBe(true);

    // 6. Identify the two cards with price 15.99 and read their names.
    const names = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    const tiedNames = names.filter((_, i) => prices[i] === 15.99).sort();
    expect(tiedNames).toEqual(['Sauce Labs Bolt T-Shirt', 'Test.allTheThings() T-Shirt (Red)'].sort());
  });

  test('Selecting Price (high to low) reorders products by descending price', async ({ page }) => {
    // 1. Start from the seed file, default az sort.
    await expect(page.locator('[data-test="product-sort-container"]')).toHaveValue('az');

    // 2. Use selectOption on the sort dropdown with value 'hilo'.
    await page.locator('[data-test="product-sort-container"]').selectOption('hilo');

    // 3. Read [data-test="active-option"] text.
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Price (high to low)');

    // 4. Parse the price text for all 6 cards in DOM order into numbers.
    const priceTexts = await page.locator('[data-test="inventory-item-price"]').allTextContents();
    const prices = priceTexts.map((p) => parseFloat(p.replace('$', '')));
    expect(prices).toEqual([49.99, 29.99, 15.99, 15.99, 9.99, 7.99]);

    // 5. Assert programmatically that the captured price array is non-increasing.
    expect(prices.every((p, i) => i === prices.length - 1 || p >= prices[i + 1])).toBe(true);

    // 6. Identify the two cards with price 15.99 and read their names.
    const names = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    const tiedNames = names.filter((_, i) => prices[i] === 15.99).sort();
    expect(tiedNames).toEqual(['Sauce Labs Bolt T-Shirt', 'Test.allTheThings() T-Shirt (Red)'].sort());
  });

  test('Switching between multiple sort options in sequence keeps list and active-option label consistent', async ({ page }) => {
    const sortDropdown = page.locator('[data-test="product-sort-container"]');
    const activeOption = page.locator('[data-test="active-option"]');
    const nameLocator = page.locator('[data-test="inventory-item-name"]');
    const priceLocator = page.locator('[data-test="inventory-item-price"]');

    // 1. Start from the seed file.
    await expect(sortDropdown).toHaveValue('az');
    const originalOrder = await nameLocator.allTextContents();

    // 2. Select 'za', then read names and active-option.
    await sortDropdown.selectOption('za');
    await expect(activeOption).toHaveText('Name (Z to A)');
    let names = await nameLocator.allTextContents();
    expect(names).toEqual([...originalOrder].sort((a, b) => b.localeCompare(a)));

    // 3. Select 'lohi', then read prices and active-option.
    await sortDropdown.selectOption('lohi');
    await expect(activeOption).toHaveText('Price (low to high)');
    let prices = (await priceLocator.allTextContents()).map((p) => parseFloat(p.replace('$', '')));
    expect(prices.every((p, i) => i === prices.length - 1 || p <= prices[i + 1])).toBe(true);

    // 4. Select 'hilo', then read prices and active-option.
    await sortDropdown.selectOption('hilo');
    await expect(activeOption).toHaveText('Price (high to low)');
    prices = (await priceLocator.allTextContents()).map((p) => parseFloat(p.replace('$', '')));
    expect(prices.every((p, i) => i === prices.length - 1 || p >= prices[i + 1])).toBe(true);

    // 5. Select 'az' again, then read names and active-option.
    await sortDropdown.selectOption('az');
    await expect(activeOption).toHaveText('Name (A to Z)');
    names = await nameLocator.allTextContents();
    expect(names).toEqual([...originalOrder].sort((a, b) => a.localeCompare(b)));
    expect(names).toEqual(originalOrder);
  });
});
