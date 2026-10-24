// spec: apps/practice-target/specs/SCRUM-202-forms-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Submit Button Transient State', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/forms');
  });

  test("Submit button is disabled and shows 'Submitting…' while the async submission is in-flight on a valid form", async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load (handled by beforeEach).

    // 2. Fill all mandatory fields with valid values.
    await page.getByTestId('input-full-name').fill('State Tester');
    await page.getByTestId('input-email').fill('state.tester@example.com');
    await page.getByTestId('input-password').fill('statePass123');
    await page.getByTestId('select-country').selectOption('Brazil');
    await page.getByTestId('checkbox-accept-terms').click();
    await expect(page.getByTestId('input-full-name')).toHaveValue('State Tester');
    await expect(page.getByTestId('input-email')).toHaveValue('state.tester@example.com');
    await expect(page.getByTestId('input-password')).toHaveValue('statePass123');
    await expect(page.getByTestId('select-country')).toHaveValue('Brazil');
    await expect(page.getByTestId('checkbox-accept-terms')).toBeChecked();

    // 3. Before clicking, assert submit-form-button is enabled and reads 'Create account'.
    const submitButton = page.getByTestId('submit-form-button');
    await expect(submitButton).toBeEnabled();
    await expect(submitButton).toHaveText('Create account');

    // 4. Click submit-form-button, then immediately read the button's disabled attribute and text.
    // No manual wait is inserted between the click and the assertions: Playwright's auto-retrying
    // expect() reliably catches the ~700-800ms "Submitting…" window when run in-process against the real page.
    await submitButton.click();
    await expect(submitButton).toBeDisabled();
    await expect(submitButton).toHaveText('Submitting…');

    // 5. Wait for form-success-alert to become visible.
    await expect(page.getByTestId('form-success-alert')).toBeVisible();
    await expect(page.getByTestId('form-success-alert')).toHaveText(
      'Submitted successfully! Registered State Tester (state.tester@example.com).'
    );
    await expect(submitButton).toBeEnabled();
    await expect(submitButton).toHaveText('Create account');
  });

  test("Submit button does NOT enter the 'Submitting…' async state when the form fails client-side validation", async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load. Leave the form empty (handled by beforeEach).

    // 2. Click submit-form-button and immediately check its text/disabled state.
    // Validation is synchronous for the failure path, so the button never enters the disabled/"Submitting…" state.
    const submitButton = page.getByTestId('submit-form-button');
    await submitButton.click();
    await expect(submitButton).toBeEnabled();
    await expect(submitButton).toHaveText('Create account');
    await expect(page.getByTestId('error-full-name')).toBeVisible();
    await expect(page.getByTestId('error-email')).toBeVisible();
    await expect(page.getByTestId('error-password')).toBeVisible();
    await expect(page.getByTestId('error-country')).toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).toBeVisible();
  });
});
