# User Story: SCRUM-201 - Authentication and Protected Dashboard

## Story Title
As a registered user, I want to log in, stay logged in and log out so that only I can reach my dashboard.

## Story Description
The app offers mock authentication with a single demo account. A successful login creates a session that lasts one hour. The session is stored in `localStorage` when "Remember me" is checked and in `sessionStorage` when it isn't. The Dashboard page is protected: anonymous visitors are redirected to the login page and sent back to the page they asked for after logging in.

## Application URL
https://custom-test-target-app.vercel.app (pages: `/login`, `/dashboard`)

## Test Credentials
- Username: `demo`
- Password: `password123`

## Acceptance Criteria

### AC1: Successful Login
- GIVEN I am on the login page and not logged in
- WHEN I enter `demo` / `password123` and click "Log in"
- THEN the button should show "Logging in…" and be disabled while the request is pending
- AND I should land on `/dashboard`
- AND I should see "Welcome back, demo." and a "Session expires at <time>" hint
- AND the navigation bar should show a `demo` user badge and a "Log out" button in place of the "Log in" link

### AC2: Failed Login
- GIVEN I am on the login page
- WHEN I submit a wrong username, a wrong password, or empty fields
- THEN I should see the error alert "Invalid username or password."
- AND I should stay on the login page
- AND the login button should be enabled again so I can retry

### AC3: Protected Route Redirect
- GIVEN I am not logged in
- WHEN I open `/dashboard` directly
- THEN I should be redirected to `/login?from=%2Fdashboard`
- AND after a successful login I should be returned to `/dashboard`

### AC4: Session Persistence
- GIVEN I log in with "Remember me" checked (the default)
- WHEN I reload the page or open the dashboard in a new tab
- THEN I should still be logged in
- GIVEN I log in with "Remember me" unchecked
- WHEN I reload the page in the same tab
- THEN I should still be logged in (session storage survives a reload)
- AND a logged-in user who visits `/login` should be redirected straight to `/dashboard`

### AC5: Logout
- GIVEN I am logged in
- WHEN I click "Log out" on the dashboard or in the navigation bar
- THEN I should be redirected to `/login`
- AND the navigation bar should show the "Log in" link again
- AND opening `/dashboard` again should redirect me to the login page

## Business Rules
1. Only `demo` / `password123` is accepted. Credentials are case-sensitive
2. A session expires one hour after login
3. "Remember me" decides whether the session uses `localStorage` (checked) or `sessionStorage` (unchecked)
4. Logout clears the session from both storages
5. The Dashboard is the only protected page. Every other page is public

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Every interactive element has a `data-testid` attribute (e.g. `login-username-input`, `login-password-input`, `login-remember-checkbox`, `login-submit-button`, `login-error`, `dashboard-welcome`, `dashboard-logout-button`, `nav-user-badge`, `nav-logout-button`, `nav-link-login`). Prefer `page.getByTestId()`
- Login is simulated with a 600 ms delay. Wait on UI state, not fixed timeouts
- Each Playwright test starts with a fresh browser context, so tests don't share a session
- Don't assert the exact expiry time. It depends on the clock and locale

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
