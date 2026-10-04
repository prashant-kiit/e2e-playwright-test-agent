# User Story: SCRUM-201 - Authentication and Protected Dashboard

## Story Title
As a registered user, I want to log in and have my dashboard protected so that only I can reach it.

## Story Description
Mock authentication with one demo account; the Dashboard is protected. (Trimmed scope: successful login plus the protected-route redirect.)

## Application URL
https://custom-test-target-app.vercel.app (pages: `/login`, `/dashboard`)

## Test Credentials
- Username: `demo`
- Password: `password123`

## Acceptance Criteria

### AC1: Successful Login (happy path)
- GIVEN I am on the login page
- WHEN I enter `demo` / `password123` and click "Log in"
- THEN I should land on `/dashboard` and see "Welcome back, demo."
- AND the nav bar should show a `demo` badge and a "Log out" button

### AC2: Protected Route Redirect (key negative)
- GIVEN I am not logged in
- WHEN I open `/dashboard` directly
- THEN I should be redirected to `/login?from=%2Fdashboard`
- AND after logging in I should be returned to `/dashboard`

## Business Rules
1. Only `demo` / `password123` is accepted
2. The Dashboard is the only protected page

## Technical Notes
- Use Playwright. Locate elements with `page.getByTestId(...)`: `login-username-input`, `login-password-input`, `login-submit-button`, `dashboard-welcome`, `nav-user-badge`, `nav-logout-button`
- Each test gets a fresh context, so it starts logged out
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
