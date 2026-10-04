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

test.describe('AC1 - Product Listing', () => {
  test.beforeEach(async ({ page }) => {
    // Repeat the seed login flow (standard_user / secret_sauce) to land on the Products page.
    await page.goto('/');
    await page.locator('[data-test="username"]').fill('standard_user');
    await page.locator('[data-test="password"]').fill('secret_sauce');
    await page.locator('[data-test="login-button"]').click();
    await expect(page).toHaveURL(/inventory\.html/);
  });

  test('Products page lists exactly 6 products with correct names and prices', async ({ page }) => {
    // 1. Start from the Products page (post-seed login state).
    await expect(page.locator('[data-test="title"]')).toHaveText('Products');
    await expect(page).toHaveURL(/inventory\.html/);

    // 2. Count the number of elements matching inventory-item inside inventory-list.
    const items = page.locator('[data-test="inventory-list"] [data-test="inventory-item"]');
    await expect(items).toHaveCount(6);

    // 3. Read the text of inventory-item-name inside each item and collect into a set.
    const names = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    expect(names).toHaveLength(6);
    expect(new Set(names)).toEqual(new Set(EXPECTED_NAMES));

    // 4. For each inventory-item, read inventory-item-price and build a name -> price map.
    const priceByName: Record<string, string> = {};
    const count = await items.count();
    for (let i = 0; i < count; i++) {
      const card = items.nth(i);
      const name = (await card.locator('[data-test="inventory-item-name"]').textContent())!;
      const price = (await card.locator('[data-test="inventory-item-price"]').textContent())!;
      priceByName[name] = price;
    }
    expect(priceByName['Sauce Labs Backpack']).toBe('$29.99');
    expect(priceByName['Sauce Labs Bike Light']).toBe('$9.99');
    expect(priceByName['Sauce Labs Bolt T-Shirt']).toBe('$15.99');
    expect(priceByName['Sauce Labs Fleece Jacket']).toBe('$49.99');
    expect(priceByName['Sauce Labs Onesie']).toBe('$7.99');
    expect(priceByName['Test.allTheThings() T-Shirt (Red)']).toBe('$15.99');
  });

  test('Each product card renders image, name, description, price, and an Add to cart button', async ({ page }) => {
    const items = page.locator('[data-test="inventory-item"]');
    const count = await items.count();
    expect(count).toBe(6);

    for (let i = 0; i < count; i++) {
      const card = items.nth(i);

      // 1. Assert presence of a visible product image via the image link.
      const imgLink = card.locator('[data-test^="item-"][data-test$="-img-link"]');
      await expect(imgLink.locator('img')).toBeVisible();

      // 2. Assert inventory-item-name is visible and matches one of the 6 expected names.
      const nameLocator = card.locator('[data-test="inventory-item-name"]');
      await expect(nameLocator).toBeVisible();
      const name = await nameLocator.textContent();
      expect(EXPECTED_NAMES).toContain(name);

      // 3. Assert inventory-item-desc is visible and non-empty.
      const descLocator = card.locator('[data-test="inventory-item-desc"]');
      await expect(descLocator).toBeVisible();
      await expect(descLocator).not.toBeEmpty();

      // 4. Assert inventory-item-price is visible and formatted as $NN.NN.
      const priceLocator = card.locator('[data-test="inventory-item-price"]');
      await expect(priceLocator).toBeVisible();
      await expect(priceLocator).toHaveText(/^\$\d+\.\d{2}$/);

      // 5. Assert the Add to cart button is visible, enabled, with the correct accessible name.
      const addButton = card.locator('button[data-test^="add-to-cart-"]');
      await expect(addButton).toBeVisible();
      await expect(addButton).toBeEnabled();
      await expect(addButton).toHaveAccessibleName('Add to cart');
    }
  });

  test('Negative: no pagination or filtering controls exist, and product count/content is stable on reload', async ({ page }) => {
    // 1. Search the DOM for pagination controls or filter inputs besides the sort dropdown.
    await expect(page.getByText('Next', { exact: true })).toHaveCount(0);
    await expect(page.getByText(/Page\s*2/)).toHaveCount(0);
    const listingControls = page.locator('main input, main select');
    await expect(listingControls).toHaveCount(1);
    await expect(listingControls).toHaveAttribute('data-test', 'product-sort-container');

    // 2. Reload the page (navigate to inventory.html again).
    await page.goto('/inventory.html');

    await expect(page.locator('[data-test="inventory-item"]')).toHaveCount(6);
    const names = await page.locator('[data-test="inventory-item-name"]').allTextContents();
    expect(new Set(names)).toEqual(new Set(EXPECTED_NAMES));
    await expect(page.locator('[data-test="product-sort-container"]')).toHaveValue('az');
    await expect(page.locator('[data-test="active-option"]')).toHaveText('Name (A to Z)');
  });
});
