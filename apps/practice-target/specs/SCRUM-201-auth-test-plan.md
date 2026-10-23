# SCRUM-201: Authentication and Protected Dashboard

## Application Overview

This test plan covers the mock authentication feature of the Playwright Practice Target app (https://custom-test-target-app.vercel.app), as specified in user story SCRUM-201. The feature provides a single demo account (demo/password123) and protects exactly one route, /dashboard, redirecting unauthenticated visitors to /login?from=%2F<path> and returning them to the originally requested page after a successful login.

All tests assume a fresh, logged-out browser context (default Playwright behavior — no stored cookies/local storage from a prior test). The app is a client-side rendered SPA; unknown routes resolve to a client-side 404 page while still returning HTTP 200, so assertions must be made on page content/testids, never on HTTP status codes or navigation response status, per the app's agent notes.

Verified against the live app during exploration:
- Login page (`/login`) testids: `login-page`, `login-demo-hint`, `login-form`, `login-username-input`, `login-password-input`, `login-remember-checkbox`, `login-submit-button`, and (only after a failed attempt) `login-error`.
- Dashboard page (`/dashboard`, protected) testids: `dashboard-page`, `dashboard-welcome`, `dashboard-session-expiry`, `dashboard-logout-button`.
- Nav bar (present on every page) testids: `brand-link`, `nav-link-home`, `nav-link-forms`, `nav-link-buttons`, `nav-link-modals`, `nav-link-dropdowns`, `nav-link-table`, `nav-link-dynamic-content`, `nav-link-navigation`, `nav-link-dashboard`. When logged out the nav bar also shows `nav-link-login`; when logged in it instead shows `nav-user-badge` and `nav-logout-button`.
- 404 page testids: `not-found-page`, `not-found-home-link`.
- Login has a brief (~1 second) simulated async delay before redirecting on both success and failure — tests must tolerate this (e.g. use Playwright's auto-waiting URL/locator assertions rather than fixed-architecture assumptions).
- Login form shows a "Remember me (persist across browser restarts)" checkbox (`login-remember-checkbox`), checked by default. This is not mentioned in the SCRUM-201 story; it is noted as an observed-but-out-of-scope UI element in this plan (not asserted on, since the story's acceptance criteria don't define its behavior).
- On a failed login (wrong username, wrong password, or any empty field combination), the app stays on `/login`, shows an alert region (`login-error`) with the exact text "Invalid username or password.", and both the entered username and password values remain in the fields except where cleared by the app itself. No native HTML5 `required` validation is used — the inputs are plain `type="text"`/`type="password"` with no `required` attribute, so empty submissions are handled entirely by app logic, producing the same "Invalid username or password." error rather than a browser validation popup.
- Clicking "Log out" (verified via `nav-logout-button`, present also as `dashboard-logout-button` in the main content) immediately logs the user out AND redirects to `/login?from=%2Fdashboard` (because /dashboard is protected and the user is no longer authenticated) rather than leaving the user on a logged-out dashboard. This confirms logout fully revokes access to the protected route.
- Direct deep-linking to `/dashboard` while logged out redirects to `/login?from=%2Fdashboard`; logging in with valid credentials from that state redirects back to `/dashboard`, confirming AC2 end-to-end.

## Test Scenarios

### 1. Authentication - Happy Path and UI State

**Seed:** `apps/practice-target/seed.spec.ts`

#### 1.1. Successful login with valid credentials lands on dashboard with full post-login UI

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Start from the seeded home page (logged out, fresh context). Navigate to /login.
    - expect: Page loads with heading 'Log in' and the login form is visible via page.getByTestId('login-form')
  2. Assert the nav bar shows page.getByTestId('nav-link-login') and does NOT show page.getByTestId('nav-user-badge') or page.getByTestId('nav-logout-button')
    - expect: Logged-out nav state confirmed before attempting login
  3. Fill page.getByTestId('login-username-input') with 'demo'
    - expect: Field shows 'demo'
  4. Fill page.getByTestId('login-password-input') with 'password123'
    - expect: Field shows the masked password
  5. Click page.getByTestId('login-submit-button')
    - expect: Login is submitted; a brief async delay (~1s) occurs before navigation (do not assert on an intermediate loading state unless independently confirmed stable)
  6. Wait for the URL to become /dashboard (e.g. expect(page).toHaveURL(/\/dashboard$/))
    - expect: Browser navigates to /dashboard
  7. Assert page.getByTestId('dashboard-welcome') contains the text 'Welcome back, demo.'
    - expect: Welcome message exactly matches 'Welcome back, demo.' including the trailing period
  8. Assert page.getByTestId('nav-user-badge') is visible and contains text 'demo'
    - expect: Nav bar badge shows the logged-in username 'demo'
  9. Assert page.getByTestId('nav-logout-button') is visible with accessible name 'Log out'
    - expect: Logout control is present in the nav bar
  10. Assert page.getByTestId('nav-link-login') is no longer present in the nav bar
    - expect: The 'Log in' nav link is replaced by the badge/logout button once authenticated
  11. Assert page.getByTestId('dashboard-page') and page.getByTestId('dashboard-session-expiry') are visible
    - expect: Dashboard page container and session-expiry text are rendered (session-expiry text content is dynamic/time-based — assert only that the element is visible and non-empty, not an exact time string)
  12. Assert page.getByTestId('dashboard-logout-button') is also visible in the main content area
    - expect: A second logout control exists in the dashboard body in addition to the nav bar one

#### 1.2. Logged-in state persists across in-app navigation to other public pages

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Log in with demo/password123 via /login as in the happy-path test, arriving at /dashboard
    - expect: User is authenticated and on /dashboard
  2. Click page.getByTestId('nav-link-home') to navigate to the home page
    - expect: Page navigates to / (home)
  3. Assert page.getByTestId('nav-user-badge') and page.getByTestId('nav-logout-button') are still visible on the home page
    - expect: Authenticated nav state is preserved across navigation to non-protected pages
  4. Navigate back to /dashboard via page.getByTestId('nav-link-dashboard')
    - expect: User lands directly on /dashboard without being redirected to /login, since the session is still active, and page.getByTestId('dashboard-welcome') is visible

### 2. Protected Route Redirect (AC2)

**Seed:** `apps/practice-target/seed.spec.ts`

#### 2.1. Direct deep link to /dashboard while logged out redirects to /login with from param

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Starting from a fresh logged-out context, navigate directly to /dashboard (deep link, not via in-app nav click)
    - expect: The app redirects client-side to /login?from=%2Fdashboard
  2. Assert the final URL is exactly '/login?from=%2Fdashboard' (e.g. expect(page).toHaveURL(/\/login\?from=%2Fdashboard$/))
    - expect: URL query parameter 'from' is correctly URL-encoded as %2Fdashboard
  3. Assert page.getByTestId('login-form') is visible and page.getByTestId('dashboard-page') is NOT present anywhere on the page
    - expect: User sees the login form, confirming /dashboard content was never rendered/leaked

#### 2.2. Logging in from the redirected state returns the user to the originally requested /dashboard

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Navigate directly to /dashboard while logged out, landing on /login?from=%2Fdashboard (per the previous test)
    - expect: On /login?from=%2Fdashboard
  2. Fill page.getByTestId('login-username-input') with 'demo' and page.getByTestId('login-password-input') with 'password123'
    - expect: Fields populated with valid credentials
  3. Click page.getByTestId('login-submit-button')
    - expect: Form submits; brief async delay before redirect
  4. Wait for the URL to become /dashboard (not /login)
    - expect: User is redirected to /dashboard, i.e. back to the page they originally tried to reach, not to a generic landing page
  5. Assert page.getByTestId('dashboard-welcome') contains 'Welcome back, demo.' and page.getByTestId('nav-user-badge') is visible
    - expect: Full authenticated dashboard state is rendered after the redirect-then-login flow

#### 2.3. Protected-route redirect also applies when the from path has query-string-unsafe characters (boundary check using /dashboard only)

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Note: per the business rules, /dashboard is the ONLY protected page in this app, so this scenario is scoped to confirming the encoding of the single protected path rather than testing multiple protected routes.
  2. Navigate directly to /dashboard while logged out
    - expect: Redirected to /login?from=%2Fdashboard
  3. Assert the raw query string value of 'from' decodes to exactly '/dashboard' (e.g. using new URL(page.url()).searchParams.get('from') === '/dashboard')
    - expect: The from parameter round-trips correctly between encode (redirect) and decode (for use after login)

### 3. Login Negative and Validation Scenarios

**Seed:** `apps/practice-target/seed.spec.ts`

#### 3.1. Wrong password with correct username shows error and does not authenticate

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Navigate to /login from a fresh logged-out context
    - expect: Login form visible, no page.getByTestId('login-error') present yet
  2. Fill page.getByTestId('login-username-input') with 'demo'
    - expect: Field shows 'demo'
  3. Fill page.getByTestId('login-password-input') with 'wrongpass'
    - expect: Field shows the masked wrong password
  4. Click page.getByTestId('login-submit-button')
    - expect: Form submits; brief async delay
  5. Wait for and assert page.getByTestId('login-error') is visible with text 'Invalid username or password.'
    - expect: Error alert appears with the exact expected copy
  6. Assert the URL is still /login (no query string change, no navigation to /dashboard)
    - expect: Authentication failure keeps the user on the login page
  7. Assert page.getByTestId('nav-link-login') is still visible in the nav bar (not nav-user-badge)
    - expect: Nav bar still reflects logged-out state after the failed attempt

#### 3.2. Wrong username with correct password shows error and does not authenticate

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Navigate to /login from a fresh logged-out context
    - expect: Login form visible
  2. Fill page.getByTestId('login-username-input') with 'wronguser'
    - expect: Field shows 'wronguser'
  3. Fill page.getByTestId('login-password-input') with 'password123'
    - expect: Field shows the masked correct password
  4. Click page.getByTestId('login-submit-button')
    - expect: Form submits; brief async delay
  5. Wait for and assert page.getByTestId('login-error') is visible with text 'Invalid username or password.'
    - expect: Error alert appears — confirms that only the exact username 'demo' is valid, matching password alone is insufficient
  6. Assert the URL is still /login
    - expect: No navigation occurred

#### 3.3. Both username and password wrong shows the same generic error

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Navigate to /login from a fresh logged-out context
    - expect: Login form visible
  2. Fill page.getByTestId('login-username-input') with 'nobody'
    - expect: Field shows 'nobody'
  3. Fill page.getByTestId('login-password-input') with 'letmein'
    - expect: Field shows the masked incorrect password
  4. Click page.getByTestId('login-submit-button')
    - expect: Form submits
  5. Assert page.getByTestId('login-error') is visible with text 'Invalid username or password.'
    - expect: Same generic error shown, not leaking which field was wrong (good security practice to verify)

#### 3.4. Empty username with valid password is rejected

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Navigate to /login from a fresh logged-out context
    - expect: Login form visible, username and password fields empty by default
  2. Leave page.getByTestId('login-username-input') empty
    - expect: Field remains empty
  3. Fill page.getByTestId('login-password-input') with 'password123'
    - expect: Field shows the masked password
  4. Click page.getByTestId('login-submit-button')
    - expect: No native browser validation popup blocks submission, since the inputs have no 'required' attribute (verified live); the app's own logic runs
  5. Assert page.getByTestId('login-error') is visible with text 'Invalid username or password.'
    - expect: Empty username is correctly treated as invalid, not as a crash or silent no-op
  6. Assert the URL remains /login and no dashboard content is rendered
    - expect: User is not authenticated

#### 3.5. Valid username with empty password is rejected

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Navigate to /login from a fresh logged-out context
    - expect: Login form visible
  2. Fill page.getByTestId('login-username-input') with 'demo'
    - expect: Field shows 'demo'
  3. Leave page.getByTestId('login-password-input') empty
    - expect: Field remains empty
  4. Click page.getByTestId('login-submit-button')
    - expect: Submission proceeds (no native required-field blocking)
  5. Assert page.getByTestId('login-error') is visible with text 'Invalid username or password.'
    - expect: Empty password is correctly treated as invalid

#### 3.6. Both username and password empty is rejected

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Navigate to /login from a fresh logged-out context
    - expect: Login form visible, both fields empty
  2. Click page.getByTestId('login-submit-button') without filling either field
    - expect: Submission proceeds (no native required-field blocking)
  3. Assert page.getByTestId('login-error') is visible with text 'Invalid username or password.'
    - expect: Fully empty submission is rejected gracefully with the same error message, not a thrown exception or blank page
  4. Assert the URL remains /login
    - expect: No navigation to /dashboard occurred

#### 3.7. A failed login attempt does not leave stale authenticated state on retry with correct credentials

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Navigate to /login from a fresh logged-out context
    - expect: Login form visible
  2. Fill username 'demo' and password 'wrongpass', then click page.getByTestId('login-submit-button')
    - expect: page.getByTestId('login-error') appears with 'Invalid username or password.'
  3. Without reloading, clear page.getByTestId('login-password-input') and fill it with the correct password 'password123'
    - expect: Password field now shows the masked correct password
  4. Click page.getByTestId('login-submit-button') again
    - expect: Second submission is processed independently of the first failed attempt
  5. Wait for URL to become /dashboard and assert page.getByTestId('dashboard-welcome') shows 'Welcome back, demo.'
    - expect: Retry with corrected credentials succeeds immediately after a prior failure, confirming the error state does not permanently lock the form

### 4. Logout and Nav Bar State

**Seed:** `apps/practice-target/seed.spec.ts`

#### 4.1. Logging out from the dashboard revokes access and redirects to login with the from=/dashboard param

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Log in with demo/password123, arriving at /dashboard
    - expect: User authenticated, dashboard visible
  2. Click page.getByTestId('nav-logout-button')
    - expect: Logout action triggers
  3. Wait for and assert the final URL is '/login?from=%2Fdashboard'
    - expect: Logging out immediately revokes the session; because /dashboard is protected and the user is no longer authenticated, the app redirects to the login page with from=/dashboard, exactly like an unauthenticated deep link would
  4. Assert page.getByTestId('login-form') is visible and page.getByTestId('nav-link-login') is shown in the nav bar (not nav-user-badge)
    - expect: Nav bar correctly reflects the logged-out state immediately after logout

#### 4.2. After logout, re-visiting /dashboard directly redirects to login again (session fully revoked)

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Log in with demo/password123, arrive at /dashboard, then click page.getByTestId('nav-logout-button') to log out
    - expect: User is redirected to /login?from=%2Fdashboard after logout
  2. Navigate directly to /dashboard again (fresh navigation, e.g. page.goto)
    - expect: App redirects again to /login?from=%2Fdashboard rather than showing any cached dashboard content
  3. Assert page.getByTestId('dashboard-welcome') is NOT present anywhere on the resulting page
    - expect: No residual authenticated state or cached protected content leaks after logout

#### 4.3. Logging out via the in-page dashboard logout button behaves the same as the nav bar logout button

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Log in with demo/password123, arriving at /dashboard
    - expect: Dashboard shows both page.getByTestId('nav-logout-button') and page.getByTestId('dashboard-logout-button')
  2. Click page.getByTestId('dashboard-logout-button') (the one in the main content area, not the nav bar)
    - expect: Logout triggers from this control as well
  3. Assert the final URL is '/login?from=%2Fdashboard' and page.getByTestId('login-form') is visible
    - expect: Both logout buttons produce identical, correct behavior

#### 4.4. Logged-out nav bar does not expose authenticated-only elements on any public page

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. Starting from a fresh logged-out context, visit / (home)
    - expect: page.getByTestId('nav-link-login') is visible; page.getByTestId('nav-user-badge') and page.getByTestId('nav-logout-button') are NOT present
  2. Navigate to /forms, /buttons, /modals, /dropdowns, /table, /dynamic, and /navigation in turn (each a public page)
    - expect: On every page, the nav bar consistently shows 'nav-link-login' and never shows 'nav-user-badge' or 'nav-logout-button' while logged out

### 5. Routing Boundary Check

**Seed:** `apps/practice-target/seed.spec.ts`

#### 5.1. Unknown path returns a client-side 404 page (not an HTTP error) and does not affect auth state

**File:** `apps/practice-target/specs/SCRUM-201-auth-test-plan.md`

**Steps:**
  1. From a fresh logged-out context, navigate directly to an unknown path such as /this-path-does-not-exist
    - expect: Per agentNotes, the app returns HTTP 200 and renders a client-side 404 page; do NOT assert on navigation/response status, only on page content
  2. Assert page.getByTestId('not-found-page') is visible with heading text '404 — Page not found'
    - expect: Correct 404 content is rendered for an unknown path
  3. Assert the nav bar still correctly shows page.getByTestId('nav-link-login') (logged-out state is unaffected by hitting an unknown route)
    - expect: Visiting an unknown path does not corrupt or change auth/nav state
  4. Click page.getByTestId('not-found-home-link')
    - expect: Navigates back to / (home) successfully, confirming the 404 page provides a working recovery path
  5. As a contrast check, log in with demo/password123 first, then navigate to the same unknown path /this-path-does-not-exist while authenticated
    - expect: The 404 page is still shown (it is not itself an auth-protected route) and the nav bar still shows page.getByTestId('nav-user-badge'), confirming the 404 handler does not interfere with or clear the authenticated session
