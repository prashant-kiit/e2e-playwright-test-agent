// spec: apps/practice-target/specs/SCRUM-202-forms-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Mandatory Field Validation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/forms');
  });

  test('No validation errors are shown before the first submit attempt', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load.
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();

    // 2. Click into input-full-name, type a few characters, then click elsewhere to blur the field without submitting.
    // The form has no live/on-blur validation (business rule 2), so no error should appear from this alone.
    await page.getByTestId('input-full-name').click();
    await page.getByTestId('input-full-name').fill('abc');
    await page.getByTestId('input-email').click();
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();

    // 3. Click into input-email and input-password, type and then clear the values, without clicking submit.
    await page.getByTestId('input-email').fill('test@test.com');
    await page.getByTestId('input-password').fill('testpass');
    await page.getByTestId('input-email').fill('');
    await page.getByTestId('input-password').fill('');
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();
  });

  test('Submitting a completely empty form shows all five mandatory field errors and no success alert', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load. Do not fill in any field (handled by beforeEach).

    // 2. Click submit-form-button.
    const submitButton = page.getByTestId('submit-form-button');
    await submitButton.click();

    // 3. Assert the following five error elements are visible with their exact text.
    await expect(page.getByTestId('error-full-name')).toHaveText('Full name is required.');
    await expect(page.getByTestId('error-email')).toHaveText('Email is required.');
    await expect(page.getByTestId('error-password')).toHaveText('Password is required.');
    await expect(page.getByTestId('error-country')).toHaveText('Please select a country.');
    await expect(page.getByTestId('error-accept-terms')).toHaveText('You must accept the terms to continue.');

    // 4. Assert that form-success-alert does not exist in the DOM.
    await expect(page.getByTestId('form-success-alert')).not.toBeVisible();

    // 5. Assert submit-form-button is enabled and shows 'Create account'.
    await expect(submitButton).toBeEnabled();
    await expect(submitButton).toHaveText('Create account');
  });

  test('Fixing only some invalid fields and resubmitting clears only the corresponding errors while leaving the rest', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load (handled by beforeEach).

    // 2. Click submit-form-button on the empty form to generate all five errors.
    const submitButton = page.getByTestId('submit-form-button');
    await submitButton.click();
    await expect(page.getByTestId('error-full-name')).toBeVisible();
    await expect(page.getByTestId('error-email')).toBeVisible();
    await expect(page.getByTestId('error-password')).toBeVisible();
    await expect(page.getByTestId('error-country')).toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).toBeVisible();

    // 3. Fill full name and email. Do NOT fill password, select a country, or check terms. Do not submit yet.
    // Errors do not auto-clear on input change, only on the next submit click, so they remain visible/unchanged here.
    await page.getByTestId('input-full-name').fill('Partial Fixer');
    await page.getByTestId('input-email').fill('partial.fixer@example.com');
    await expect(page.getByTestId('error-full-name')).toHaveText('Full name is required.');
    await expect(page.getByTestId('error-email')).toHaveText('Email is required.');

    // 4. Click submit-form-button again.
    await submitButton.click();
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('error-password')).toHaveText('Password is required.');
    await expect(page.getByTestId('error-country')).toHaveText('Please select a country.');
    await expect(page.getByTestId('error-accept-terms')).toHaveText('You must accept the terms to continue.');
    await expect(page.getByTestId('form-success-alert')).not.toBeVisible();
  });
});
