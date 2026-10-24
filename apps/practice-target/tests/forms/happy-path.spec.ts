// spec: apps/practice-target/specs/SCRUM-202-forms-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Happy Path - Successful Submission', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/forms');
  });

  test('Submitting the form with all mandatory fields filled shows Submitting state then success alert', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load.
    await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible();
    await expect(page.getByTestId('signup-form')).toBeVisible();

    // 2. Assert the initial state of the form before any interaction.
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();
    await expect(page.getByTestId('form-success-alert')).not.toBeVisible();
    const submitButton = page.getByTestId('submit-form-button');
    await expect(submitButton).toBeEnabled();
    await expect(submitButton).toHaveText('Create account');

    // 3. Fill input-full-name with 'Jane Tester'.
    await page.getByTestId('input-full-name').fill('Jane Tester');
    await expect(page.getByTestId('input-full-name')).toHaveValue('Jane Tester');

    // 4. Fill input-email with 'jane.tester@example.com'.
    await page.getByTestId('input-email').fill('jane.tester@example.com');
    await expect(page.getByTestId('input-email')).toHaveValue('jane.tester@example.com');

    // 5. Fill input-password with a valid password of 12 characters.
    await page.getByTestId('input-password').fill('validPass123');
    await expect(page.getByTestId('input-password')).toHaveValue('validPass123');

    // 6. Select 'India' from select-country using selectOption, since this is a native HTML <select>.
    await page.getByTestId('select-country').selectOption('India');
    await expect(page.getByTestId('select-country')).toHaveValue('India');

    // 7. Click checkbox-accept-terms to check it.
    await page.getByTestId('checkbox-accept-terms').click();
    await expect(page.getByTestId('checkbox-accept-terms')).toBeChecked();

    // 8. Leave all optional fields untouched at their defaults (no action required).

    // 9. Click submit-form-button. Immediately after the click, the button becomes disabled and reads 'Submitting…'.
    // No wait is needed between click and assertion: Playwright's auto-retrying expect() correctly
    // catches the ~700-800ms transient window when run in-process (unlike slower manual exploration tools).
    await submitButton.click();
    await expect(submitButton).toBeDisabled();
    await expect(submitButton).toHaveText('Submitting…');
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();

    // 10. Wait for the submission to resolve.
    await expect(page.getByTestId('form-success-alert')).toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toHaveText(
      'Submitted successfully! Registered Jane Tester (jane.tester@example.com).'
    );
    await expect(submitButton).toBeEnabled();
    await expect(submitButton).toHaveText('Create account');
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();
  });

  test('Submitting with only mandatory fields filled (all optional fields left blank/default) still succeeds', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load (handled by beforeEach).

    // 2. Fill the five mandatory fields; leave all optional fields untouched.
    await page.getByTestId('input-full-name').fill('Alex Optional');
    await page.getByTestId('input-email').fill('alex.optional@example.com');
    await page.getByTestId('input-password').fill('optionalPass1');
    await page.getByTestId('select-country').selectOption('United Kingdom');
    await page.getByTestId('checkbox-accept-terms').click();
    await expect(page.getByTestId('input-full-name')).toHaveValue('Alex Optional');
    await expect(page.getByTestId('input-email')).toHaveValue('alex.optional@example.com');
    await expect(page.getByTestId('input-password')).toHaveValue('optionalPass1');
    await expect(page.getByTestId('select-country')).toHaveValue('United Kingdom');
    await expect(page.getByTestId('checkbox-accept-terms')).toBeChecked();

    // 3. Click submit-form-button and wait for the async submission to resolve.
    const submitButton = page.getByTestId('submit-form-button');
    await submitButton.click();
    await expect(page.getByTestId('form-success-alert')).toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toHaveText(
      'Submitted successfully! Registered Alex Optional (alex.optional@example.com).'
    );
    await expect(submitButton).toHaveText('Create account');
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();
  });

  test('Password at exactly the 8-character minimum boundary is accepted', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load (handled by beforeEach).

    // 2. Fill mandatory fields with a password of exactly 8 characters.
    await page.getByTestId('input-full-name').fill('Boundary Tester');
    await page.getByTestId('input-email').fill('boundary.tester@example.com');
    await page.getByTestId('input-password').fill('abcd1234');
    await page.getByTestId('select-country').selectOption('Japan');
    await page.getByTestId('checkbox-accept-terms').click();
    await expect(page.getByTestId('input-password')).toHaveValue('abcd1234');

    // 3. Click submit-form-button and wait for the submission to resolve.
    await page.getByTestId('submit-form-button').click();
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toHaveText(
      'Submitted successfully! Registered Boundary Tester (boundary.tester@example.com).'
    );
  });
});
