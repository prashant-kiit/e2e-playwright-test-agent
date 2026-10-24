// spec: apps/practice-target/specs/SCRUM-202-forms-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('UI Element Presence and Labeling', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/forms');
  });

  test('All sign-up form fields and controls render with correct labels/types on page load', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load (handled by beforeEach).

    // 2. Assert the 'Create account' heading is visible and the signup-form element is present.
    await expect(page.getByRole('heading', { name: 'Create account' })).toBeVisible();
    await expect(page.getByTestId('signup-form')).toBeVisible();

    // 3. Assert input-full-name is visible, is an empty text input, associated with the 'Full name' label.
    const fullName = page.getByTestId('input-full-name');
    await expect(fullName).toBeVisible();
    await expect(fullName).toHaveAttribute('type', 'text');
    await expect(fullName).toHaveValue('');
    await expect(page.getByText('Full name', { exact: true })).toBeVisible();

    // 4. Assert input-email is visible, is an empty input of type email, associated with the 'Email' label.
    const email = page.getByTestId('input-email');
    await expect(email).toBeVisible();
    await expect(email).toHaveAttribute('type', 'email');
    await expect(email).toHaveValue('');
    await expect(page.getByText('Email', { exact: true })).toBeVisible();

    // 5. Assert input-password is visible, is an empty input of type password, with helper text nearby.
    const password = page.getByTestId('input-password');
    await expect(password).toBeVisible();
    await expect(password).toHaveAttribute('type', 'password');
    await expect(password).toHaveValue('');
    await expect(page.getByText('Password', { exact: true })).toBeVisible();
    await expect(page.getByText('Minimum 8 characters.')).toBeVisible();

    // 6. Assert toggle-password-visibility button is visible, and toggles the password field's type attribute.
    const toggle = page.getByTestId('toggle-password-visibility');
    await expect(toggle).toBeVisible();
    await expect(toggle).toHaveText('Show');
    await toggle.click();
    await expect(password).toHaveAttribute('type', 'text');
    await expect(toggle).toHaveText('Hide');
    await toggle.click();
    await expect(password).toHaveAttribute('type', 'password');
    await expect(toggle).toHaveText('Show');

    // 7. Assert select-country is a native <select> with the placeholder selected by default and six country options.
    const country = page.getByTestId('select-country');
    await expect(country).toBeVisible();
    expect(await country.evaluate((el) => el.tagName)).toBe('SELECT');
    await expect(country).toHaveValue('');
    await expect(page.getByRole('option', { name: 'Select a country…' })).toHaveAttribute('value', '');
    // Non-selected <option> elements inside a closed native <select> are reported as
    // "hidden" by Chromium's accessibility tree even though they are present and
    // selectable, so assert attachment/content rather than visibility here.
    await expect(country.locator('option')).toHaveCount(7);
    await expect(page.getByRole('option', { name: 'United States' })).toBeAttached();
    await expect(page.getByRole('option', { name: 'United Kingdom' })).toBeAttached();
    await expect(page.getByRole('option', { name: 'India' })).toBeAttached();
    await expect(page.getByRole('option', { name: 'Germany' })).toBeAttached();
    await expect(page.getByRole('option', { name: 'Japan' })).toBeAttached();
    await expect(page.getByRole('option', { name: 'Brazil' })).toBeAttached();

    // 8. Assert checkbox-accept-terms is visible, of type checkbox, unchecked by default, with its label.
    const terms = page.getByTestId('checkbox-accept-terms');
    await expect(terms).toBeVisible();
    await expect(terms).toHaveAttribute('type', 'checkbox');
    await expect(terms).not.toBeChecked();
    await expect(page.getByText('I accept the terms and conditions')).toBeVisible();

    // 9. Assert submit-form-button and reset-form-button are visible with correct default labels.
    const submitButton = page.getByTestId('submit-form-button');
    await expect(submitButton).toBeVisible();
    await expect(submitButton).toBeEnabled();
    await expect(submitButton).toHaveText('Create account');
    const resetButton = page.getByTestId('reset-form-button');
    await expect(resetButton).toBeVisible();
    await expect(resetButton).toHaveText('Reset');

    // 10. Assert the optional fields are present with their documented default values/states.
    await expect(page.getByTestId('input-age')).toHaveAttribute('type', 'number');
    await expect(page.getByTestId('input-bio')).toBeVisible();
    expect(await page.getByTestId('input-bio').evaluate((el) => el.tagName)).toBe('TEXTAREA');
    await expect(page.getByTestId('radio-plan-basic')).toBeChecked();
    await expect(page.getByTestId('radio-plan-pro')).not.toBeChecked();
    await expect(page.getByTestId('radio-plan-enterprise')).not.toBeChecked();
    await expect(page.getByTestId('checkbox-interest-automation')).not.toBeChecked();
    await expect(page.getByTestId('checkbox-interest-design')).not.toBeChecked();
    await expect(page.getByTestId('checkbox-interest-performance')).not.toBeChecked();
    await expect(page.getByTestId('checkbox-interest-accessibility')).not.toBeChecked();
    await expect(page.getByTestId('checkbox-interest-security')).not.toBeChecked();
    const experienceRange = page.getByTestId('input-experience-range');
    await expect(experienceRange).toHaveAttribute('type', 'range');
    await expect(experienceRange).toHaveValue('3');
    await expect(page.getByTestId('input-start-date')).toHaveAttribute('type', 'date');
    await expect(page.getByTestId('input-resume-upload')).toHaveAttribute('type', 'file');
  });

  test('Reset button clears user-entered values and any shown validation errors', async ({ page }) => {
    // 1. Navigate to /forms with a fresh page load (handled by beforeEach).

    // 2. Fill full name and email, then submit the otherwise-empty form to generate the remaining errors.
    await page.getByTestId('input-full-name').fill('Temp Value');
    await page.getByTestId('input-email').fill('temp@example.com');
    await page.getByTestId('submit-form-button').click();
    await expect(page.getByTestId('error-password')).toBeVisible();
    await expect(page.getByTestId('error-country')).toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).toBeVisible();
    await expect(page.getByTestId('error-full-name')).not.toBeVisible();
    await expect(page.getByTestId('error-email')).not.toBeVisible();

    // 3. Click reset-form-button.
    // Observed live behavior: Reset also clears any currently-shown error-* elements, in addition to field values.
    await page.getByTestId('reset-form-button').click();
    await expect(page.getByTestId('input-full-name')).toHaveValue('');
    await expect(page.getByTestId('input-email')).toHaveValue('');
    await expect(page.getByTestId('error-password')).not.toBeVisible();
    await expect(page.getByTestId('error-country')).not.toBeVisible();
    await expect(page.getByTestId('error-accept-terms')).not.toBeVisible();
    await expect(page.getByTestId('select-country')).toHaveValue('');
    await expect(page.getByTestId('checkbox-accept-terms')).not.toBeChecked();
  });
});
