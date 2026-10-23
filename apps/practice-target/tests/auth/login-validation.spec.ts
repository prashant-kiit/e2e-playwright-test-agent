// spec: apps/practice-target/specs/SCRUM-201-auth-test-plan.md
// seed: apps/practice-target/seed.spec.ts

import { test, expect } from '@playwright/test';

test.describe('Login Negative and Validation Scenarios', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('home-page')).toBeVisible();
    await expect(page.getByTestId('status-badge')).toHaveText('online');
  });

  test('Wrong password with correct username shows error and does not authenticate', async ({ page }) => {
    // 1. Navigate to /login from a fresh logged-out context
    await page.goto('/login');
    await expect(page.getByTestId('login-form')).toBeVisible();
    await expect(page.getByTestId('login-error')).not.toBeVisible();

    // 2. Fill login-username-input with 'demo'
    await page.getByTestId('login-username-input').fill('demo');

    // 3. Fill login-password-input with 'wrongpass'
    await page.getByTestId('login-password-input').fill('wrongpass');

    // 4. Click login-submit-button
    await page.getByTestId('login-submit-button').click();

    // 5. Wait for and assert login-error is visible with text 'Invalid username or password.'
    // (brief ~1s async delay on failure too; the auto-waiting assertion tolerates it)
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-error')).toHaveText('Invalid username or password.');

    // 6. Assert the URL is still /login (no query string change, no navigation to /dashboard)
    await expect(page).toHaveURL('/login');

    // 7. Assert nav-link-login is still visible in the nav bar (not nav-user-badge)
    await expect(page.getByTestId('nav-link-login')).toBeVisible();
    await expect(page.getByTestId('nav-user-badge')).not.toBeVisible();
  });

  test('Wrong username with correct password shows error and does not authenticate', async ({ page }) => {
    // 1. Navigate to /login from a fresh logged-out context
    await page.goto('/login');
    await expect(page.getByTestId('login-form')).toBeVisible();

    // 2. Fill login-username-input with 'wronguser'
    await page.getByTestId('login-username-input').fill('wronguser');

    // 3. Fill login-password-input with 'password123'
    await page.getByTestId('login-password-input').fill('password123');

    // 4. Click login-submit-button
    await page.getByTestId('login-submit-button').click();

    // 5. Wait for and assert login-error is visible with text 'Invalid username or password.'
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-error')).toHaveText('Invalid username or password.');

    // 6. Assert the URL is still /login
    await expect(page).toHaveURL('/login');
  });

  test('Both username and password wrong shows the same generic error', async ({ page }) => {
    // 1. Navigate to /login from a fresh logged-out context
    await page.goto('/login');
    await expect(page.getByTestId('login-form')).toBeVisible();

    // 2. Fill login-username-input with 'nobody'
    await page.getByTestId('login-username-input').fill('nobody');

    // 3. Fill login-password-input with 'letmein'
    await page.getByTestId('login-password-input').fill('letmein');

    // 4. Click login-submit-button
    await page.getByTestId('login-submit-button').click();

    // 5. Assert login-error is visible with text 'Invalid username or password.'
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-error')).toHaveText('Invalid username or password.');
  });

  test('Empty username with valid password is rejected', async ({ page }) => {
    // 1. Navigate to /login from a fresh logged-out context
    await page.goto('/login');
    await expect(page.getByTestId('login-form')).toBeVisible();
    await expect(page.getByTestId('login-username-input')).toHaveValue('');
    await expect(page.getByTestId('login-password-input')).toHaveValue('');

    // 2. Leave login-username-input empty

    // 3. Fill login-password-input with 'password123'
    await page.getByTestId('login-password-input').fill('password123');

    // 4. Click login-submit-button (no native 'required' validation blocks submission)
    await page.getByTestId('login-submit-button').click();

    // 5. Assert login-error is visible with text 'Invalid username or password.'
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-error')).toHaveText('Invalid username or password.');

    // 6. Assert the URL remains /login and no dashboard content is rendered
    await expect(page).toHaveURL('/login');
    await expect(page.getByTestId('dashboard-page')).not.toBeVisible();
  });

  test('Valid username with empty password is rejected', async ({ page }) => {
    // 1. Navigate to /login from a fresh logged-out context
    await page.goto('/login');
    await expect(page.getByTestId('login-form')).toBeVisible();

    // 2. Fill login-username-input with 'demo'
    await page.getByTestId('login-username-input').fill('demo');

    // 3. Leave login-password-input empty

    // 4. Click login-submit-button (no native required-field blocking)
    await page.getByTestId('login-submit-button').click();

    // 5. Assert login-error is visible with text 'Invalid username or password.'
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-error')).toHaveText('Invalid username or password.');
  });

  test('Both username and password empty is rejected', async ({ page }) => {
    // 1. Navigate to /login from a fresh logged-out context
    await page.goto('/login');
    await expect(page.getByTestId('login-form')).toBeVisible();

    // 2. Click login-submit-button without filling either field (no native required-field blocking)
    await page.getByTestId('login-submit-button').click();

    // 3. Assert login-error is visible with text 'Invalid username or password.'
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-error')).toHaveText('Invalid username or password.');

    // 4. Assert the URL remains /login
    await expect(page).toHaveURL('/login');
  });

  test('A failed login attempt does not leave stale authenticated state on retry with correct credentials', async ({ page }) => {
    // 1. Navigate to /login from a fresh logged-out context
    await page.goto('/login');
    await expect(page.getByTestId('login-form')).toBeVisible();

    // 2. Fill username 'demo' and password 'wrongpass', then click login-submit-button
    await page.getByTestId('login-username-input').fill('demo');
    await page.getByTestId('login-password-input').fill('wrongpass');
    await page.getByTestId('login-submit-button').click();
    await expect(page.getByTestId('login-error')).toBeVisible();
    await expect(page.getByTestId('login-error')).toHaveText('Invalid username or password.');

    // 3. Without reloading, clear login-password-input and fill it with the correct password 'password123'
    await page.getByTestId('login-password-input').fill('password123');
    await expect(page.getByTestId('login-password-input')).toHaveValue('password123');

    // 4. Click login-submit-button again
    await page.getByTestId('login-submit-button').click();

    // 5. Wait for URL to become /dashboard and assert dashboard-welcome shows 'Welcome back, demo.'
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByTestId('dashboard-welcome')).toHaveText('Welcome back, demo.');
  });
});
