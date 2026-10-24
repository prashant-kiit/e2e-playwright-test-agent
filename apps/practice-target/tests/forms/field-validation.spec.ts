// spec: apps/practice-target/specs/SCRUM-202-forms-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Field-Level Boundary and Format Validation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/forms');
  });

  test('Password below the 8-character minimum shows a dedicated length error on submit', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load (handled by beforeEach).

    // 2. Fill all mandatory fields with a 7-character password.
    await page.getByTestId('input-full-name').fill('Jane Tester');
    await page.getByTestId('input-email').fill('jane.tester@example.com');
    await page.getByTestId('input-password').fill('abc1234');
    await page.getByTestId('select-country').selectOption('India');
    await page.getByTestId('checkbox-accept-terms').click();
    await expect(page.getByTestId('input-password')).toHaveValue('abc1234');

    // 3. Click submit-form-button.
    const submitButton = page.getByTestId('submit-form-button');
    await submitButton.click();
    await expect(page.getByTestId('error-password')).toHaveText('Password must be at least 8 characters.');
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();
    await expect(page.getByTestId('form-success-alert')).not.toBeVisible();

    // 4. Without clicking submit again, update input-password to a valid 8+ character value.
    // Errors only re-evaluate on the next submit click, not live as you type, so the stale error persists.
    await page.getByTestId('input-password').fill('abc12345');
    await expect(page.getByTestId('error-password')).toHaveText('Password must be at least 8 characters.');

    // 5. Click submit-form-button again and wait for the async submission to resolve.
    await submitButton.click();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toHaveText(
      'Submitted successfully! Registered Jane Tester (jane.tester@example.com).'
    );
  });

  test('Invalid email format shows a format-specific error distinct from the required-field error', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load (handled by beforeEach).

    // 2. Fill all mandatory fields with an invalid email format.
    await page.getByTestId('input-full-name').fill('Jane Tester');
    await page.getByTestId('input-email').fill('not-an-email');
    await page.getByTestId('input-password').fill('validpass123');
    await page.getByTestId('select-country').selectOption('Germany');
    await page.getByTestId('checkbox-accept-terms').click();
    await expect(page.getByTestId('input-email')).toHaveValue('not-an-email');

    // 3. Click submit-form-button.
    const submitButton = page.getByTestId('submit-form-button');
    await submitButton.click();
    await expect(page.getByTestId('error-email')).toHaveText('Enter a valid email address.');
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();
    await expect(page.getByTestId('form-success-alert')).not.toBeVisible();

    // 4. Fix input-email to a valid value and click submit-form-button again, waiting for the submission to resolve.
    await page.getByTestId('input-email').fill('jane.tester@example.com');
    await submitButton.click();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toHaveText(
      'Submitted successfully! Registered Jane Tester (jane.tester@example.com).'
    );
  });
});
