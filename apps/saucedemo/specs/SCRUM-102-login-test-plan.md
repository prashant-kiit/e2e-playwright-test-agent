# SCRUM-102 Login and Logout Test Plan

## Application Overview

## SauceDemo Login & Logout - SCRUM-102

**Application Under Test:** https://www.saucedemo.com (Swag Labs)
**Login page URL:** `/` (root)
**Protected page used for verification:** `/inventory.html` (title: "Products")

### Starting state assumption
All scenarios in this plan assume a **fresh, unauthenticated browser context** starting at `page.goto('/')`, UNLESS the scenario explicitly requires a logged-in state as a precondition (e.g. the Logout tests), in which case the precondition step is spelled out explicitly within the test (do not rely on any seed/global login for this story).

### Credentials used across this plan
| User | Password | Expected outcome |
|---|---|---|
| `standard_user` | `secret_sauce` | Successful login |
| `locked_out_user` | `secret_sauce` | Locked-out error |
| `problem_user` | `secret_sauce` | Successful login (other defects out of scope) |
| `performance_glitch_user` | `secret_sauce` | Successful login (slow but succeeds, out of scope) |
| `error_user` | `secret_sauce` | Successful login (other defects out of scope) |
| `visual_user` | `secret_sauce` | Successful login (other defects out of scope) |

### Key stable locators discovered during exploration
| Element | Locator |
|---|---|
| Username field | `[data-test="username"]` |
| Password field | `[data-test="password"]` |
| Login button | `[data-test="login-button"]` |
| Error message banner | `[data-test="error"]` (role="alert") |
| Error dismiss (X) button | `[data-test="error-button"]` |
| Accepted usernames list | `[data-test="login-credentials"]` |
| Shared password hint | `[data-test="login-password"]` |
| Products page title | `[data-test="title"]` (text "Products") |
| Open Menu button | `getByRole('button', { name: 'Open Menu' })` (do NOT use `[data-test="open-menu"]`, it times out; do NOT JS-click, leaves items aria-hidden) |
| Logout link (in side menu) | `[data-test="logout-sidebar-link"]` |

### Verified application behaviors (from manual exploration)
- Clicking Login with both fields empty shows: "Epic sadface: Username is required". Both username and password inputs gain an `error` CSS class (full class becomes `input_error form_input error`; base class `input_error form_input` is always present regardless of error state, so assertions must check for the specific `error` token, not just substring `input_error`).
- Valid username + empty password shows: "Epic sadface: Password is required", with the same field error-class behavior.
- Wrong username and/or wrong password (both non-empty) shows: "Epic sadface: Username and password do not match any user in this service".
- `locked_out_user` + `secret_sauce` shows: "Epic sadface: Sorry, this user has been locked out." Username/password values typed remain in the fields; user stays on `/`.
- Clicking the error dismiss button (`[data-test="error-button"]`) removes the `[data-test="error"]` alert AND removes the `error` class token from both input fields, while preserving whatever text was already typed into the fields.
- Successful login (`standard_user`/`secret_sauce`) via clicking Login OR via pressing Enter in the password field navigates to `/inventory.html` with page heading "Products" (`[data-test="title"]`).
- Username matching is case-sensitive: `Standard_User`/`secret_sauce` fails with the "do not match any user" error.
- Leading/trailing whitespace in username or password is taken literally (NOT trimmed) by the app; ` standard_user `/` secret_sauce ` fails with "do not match any user" error.
- Navigating directly to `/inventory.html` without being logged in redirects to `/` and shows: "Epic sadface: You can only access '/inventory.html' when you are logged in."
- After logging in and then using the side-menu Logout link (`[data-test="logout-sidebar-link"]`, reached via `getByRole('button', { name: 'Open Menu' })`), the app returns to `/` (login page, no error shown).
- After logout, pressing the browser Back button does NOT restore the products page; it redirects back to `/` and re-shows the protected-page error: "Epic sadface: You can only access '/inventory.html' when you are logged in."
- Other accepted users (`problem_user`, `performance_glitch_user`, `error_user`, `visual_user`) all successfully authenticate and land on `/inventory.html`; any other visual/functional defects for these users are explicitly out of scope for this story.

## Test Scenarios

### 1. AC1 - Successful Login

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 1.1. Login page displays all required elements

**File:** `apps/saucedemo/specs/AC1-successful-login.spec.ts`

**Steps:**
  1. Navigate to the base URL '/' with a fresh, unauthenticated browser context.
    - expect: Page loads the login form without redirect
    - expect: URL is exactly '/' (or base URL with no path)
  2. Assert the username field '[data-test="username"]' is visible and empty.
    - expect: Field is visible and has empty value
  3. Assert the password field '[data-test="password"]' is visible and empty.
    - expect: Field is visible and has empty value
  4. Assert the Login button '[data-test="login-button"]' is visible and enabled.
    - expect: Button is visible and enabled
  5. Assert the accepted usernames panel '[data-test="login-credentials"]' is visible and contains text 'standard_user', 'locked_out_user', 'problem_user', 'performance_glitch_user', 'error_user', 'visual_user'.
    - expect: All six usernames are listed in the panel text
  6. Assert the shared password panel '[data-test="login-password"]' is visible and contains text 'secret_sauce'.
    - expect: Panel shows 'secret_sauce' as the password for all users
  7. Assert no error alert '[data-test="error"]' is present on initial page load.
    - expect: Error alert element is not present/visible

#### 1.2. Successful login via Login button click with standard_user

**File:** `apps/saucedemo/specs/AC1-successful-login.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'standard_user'.
    - expect: Field contains 'standard_user'
  3. Fill '[data-test="password"]' with 'secret_sauce'.
    - expect: Field contains 'secret_sauce'
  4. Click '[data-test="login-button"]'.
    - expect: Navigation occurs to '/inventory.html'
    - expect: Page heading '[data-test="title"]' has text 'Products'
    - expect: No error alert is shown

#### 1.3. Successful login via Enter key in password field with standard_user

**File:** `apps/saucedemo/specs/AC1-successful-login.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'standard_user'.
    - expect: Field contains 'standard_user'
  3. Click into '[data-test="password"]', type 'secret_sauce', then press Enter.
    - expect: Form submits without clicking the Login button
    - expect: Navigation occurs to '/inventory.html'
    - expect: Page heading '[data-test="title"]' has text 'Products'

#### 1.4. Successful login for each of the other accepted users (problem_user, performance_glitch_user, error_user, visual_user)

**File:** `apps/saucedemo/specs/AC1-successful-login.spec.ts`

**Steps:**
  1. Parameterize the test over the user list: ['problem_user','performance_glitch_user','error_user','visual_user']. For each user, navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with the current user and '[data-test="password"]' with 'secret_sauce'. Click '[data-test="login-button"]'.
    - expect: Navigation occurs to '/inventory.html' for every user in the list
    - expect: Page heading '[data-test="title"]' has text 'Products'
    - expect: No error alert is shown
    - expect: Note: Do NOT assert on any other page content/behavior for these users - their other defects are out of scope for this story

### 2. AC2 - Failed Login Validation Messages

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 2.1. Empty username and empty password shows 'Username is required' error

**File:** `apps/saucedemo/specs/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown, both fields empty
  2. Without filling any field, click '[data-test="login-button"]'.
    - expect: URL remains '/' (no navigation)
    - expect: Error alert '[data-test="error"]' is visible with text 'Epic sadface: Username is required'
    - expect: Username field '[data-test="username"]' class attribute contains the token 'error'
    - expect: Password field '[data-test="password"]' class attribute contains the token 'error'

#### 2.2. Valid username with empty password shows 'Password is required' error

**File:** `apps/saucedemo/specs/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'standard_user'. Leave password empty. Click '[data-test="login-button"]'.
    - expect: URL remains '/' (no navigation)
    - expect: Error alert '[data-test="error"]' is visible with text 'Epic sadface: Password is required'
    - expect: Username field retains value 'standard_user'
    - expect: Both username and password fields carry the error class token

#### 2.3. Wrong username and wrong password shows generic mismatch error

**File:** `apps/saucedemo/specs/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'wrong_user' and '[data-test="password"]' with 'wrong_pass'. Click '[data-test="login-button"]'.
    - expect: URL remains '/' (no navigation)
    - expect: Error alert '[data-test="error"]' is visible with text 'Epic sadface: Username and password do not match any user in this service'
    - expect: Both fields carry the error class token
    - expect: Typed values remain visible in the fields

#### 2.4. Valid username with wrong password shows generic mismatch error

**File:** `apps/saucedemo/specs/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'standard_user' and '[data-test="password"]' with 'wrong_pass'. Click '[data-test="login-button"]'.
    - expect: URL remains '/' (no navigation)
    - expect: Error alert shows text 'Epic sadface: Username and password do not match any user in this service'

#### 2.5. Username is case-sensitive (wrong-case valid username fails)

**File:** `apps/saucedemo/specs/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'Standard_User' (capitalized) and '[data-test="password"]' with 'secret_sauce'. Click '[data-test="login-button"]'.
    - expect: URL remains '/' (no navigation to inventory)
    - expect: Error alert shows text 'Epic sadface: Username and password do not match any user in this service'
    - expect: Confirms username matching is case-sensitive

#### 2.6. Leading/trailing whitespace in credentials is not trimmed and causes login failure

**File:** `apps/saucedemo/specs/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with ' standard_user ' (leading and trailing space) and '[data-test="password"]' with ' secret_sauce ' (leading and trailing space). Click '[data-test="login-button"]'.
    - expect: URL remains '/' (no navigation)
    - expect: Error alert shows text 'Epic sadface: Username and password do not match any user in this service'
    - expect: Confirms the app takes credentials literally and does not trim whitespace

#### 2.7. Password-only whitespace with valid username still fails

**File:** `apps/saucedemo/specs/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'standard_user' and '[data-test="password"]' with a single space ' '. Click '[data-test="login-button"]'.
    - expect: URL remains '/' (no navigation)
    - expect: Error alert shows text 'Epic sadface: Username and password do not match any user in this service' (password is non-empty so the required-field check is bypassed, but the value does not match)

### 3. AC3 - Locked-Out User

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 3.1. locked_out_user cannot log in and sees locked-out message

**File:** `apps/saucedemo/specs/AC3-locked-out-user.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'locked_out_user' and '[data-test="password"]' with 'secret_sauce'. Click '[data-test="login-button"]'.
    - expect: URL remains '/' (no navigation to '/inventory.html')
    - expect: Error alert '[data-test="error"]' is visible with exact text 'Epic sadface: Sorry, this user has been locked out.'
    - expect: Typed username and password values remain visible in the respective fields

#### 3.2. locked_out_user via Enter key also fails with locked-out message

**File:** `apps/saucedemo/specs/AC3-locked-out-user.spec.ts`

**Steps:**
  1. Navigate to '/'.
    - expect: Login page is shown
  2. Fill '[data-test="username"]' with 'locked_out_user'. Click into '[data-test="password"]', type 'secret_sauce', press Enter.
    - expect: URL remains '/' (no navigation)
    - expect: Error alert shows text 'Epic sadface: Sorry, this user has been locked out.'

#### 3.3. Re-attempting login as locked_out_user after dismissing the error still fails

**File:** `apps/saucedemo/specs/AC3-locked-out-user.spec.ts`

**Steps:**
  1. Navigate to '/'. Fill in 'locked_out_user' / 'secret_sauce' and click Login.
    - expect: Locked-out error is shown
  2. Click the dismiss (X) button '[data-test="error-button"]', then click '[data-test="login-button"]' again without changing any field.
    - expect: Error alert reappears with the same locked-out message
    - expect: User remains on '/'

### 4. AC4 - Error Message Dismissal

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 4.1. Dismissing a required-field error clears the message and field error styling

**File:** `apps/saucedemo/specs/AC4-error-dismissal.spec.ts`

**Steps:**
  1. Navigate to '/'. Click '[data-test="login-button"]' with both fields empty to trigger the 'Username is required' error.
    - expect: Error alert '[data-test="error"]' is visible
    - expect: Both input fields carry the error class token
  2. Click the dismiss button '[data-test="error-button"]' (the X icon inside the alert).
    - expect: Error alert '[data-test="error"]' is no longer present/visible
    - expect: Username field class no longer contains the 'error' token
    - expect: Password field class no longer contains the 'error' token

#### 4.2. Dismissing a mismatch error preserves already-typed field values

**File:** `apps/saucedemo/specs/AC4-error-dismissal.spec.ts`

**Steps:**
  1. Navigate to '/'. Fill username 'wrong_user' and password 'wrong_pass'. Click Login.
    - expect: Error alert is visible with the 'do not match any user' message
  2. Click '[data-test="error-button"]' to dismiss the error.
    - expect: Error alert disappears
    - expect: Username field still contains 'wrong_user'
    - expect: Password field still contains 'wrong_pass'
    - expect: User remains on '/'

#### 4.3. Dismissing the locked-out error allows retyping credentials without a stale error reappearing

**File:** `apps/saucedemo/specs/AC4-error-dismissal.spec.ts`

**Steps:**
  1. Navigate to '/'. Log in with 'locked_out_user' / 'secret_sauce'.
    - expect: Locked-out error alert is visible
  2. Click '[data-test="error-button"]' to dismiss.
    - expect: Error alert disappears
  3. Clear the username field and fill it with 'standard_user', keep password 'secret_sauce', click Login.
    - expect: Login succeeds and navigates to '/inventory.html'
    - expect: No locked-out error is shown at any point during or after this new attempt

### 5. AC5 - Protected Pages and Logout

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 5.1. Direct navigation to /inventory.html while logged out redirects to login with protected-page error

**File:** `apps/saucedemo/specs/AC5-protected-pages-logout.spec.ts`

**Steps:**
  1. Using a fresh, unauthenticated browser context, navigate directly to '/inventory.html' (do not go through the login form).
    - expect: Browser is redirected to '/' (login page), NOT '/inventory.html'
    - expect: Error alert '[data-test="error"]' is visible with exact text "Epic sadface: You can only access '/inventory.html' when you are logged in."
    - expect: Login form fields are empty

#### 5.2. Logged-in user can log out via the side menu and returns to the login page

**File:** `apps/saucedemo/specs/AC5-protected-pages-logout.spec.ts`

**Steps:**
  1. Navigate to '/'. Log in with 'standard_user' / 'secret_sauce'.
    - expect: Navigation to '/inventory.html' succeeds, heading shows 'Products'
  2. Click the menu button via getByRole('button', { name: 'Open Menu' }) (do not use '[data-test="open-menu"]' or a JS click).
    - expect: Side menu opens and becomes visible (not aria-hidden)
    - expect: '[data-test="logout-sidebar-link"]' is visible with text 'Logout'
  3. Click '[data-test="logout-sidebar-link"]'.
    - expect: Browser navigates back to '/' (login page)
    - expect: No error alert is shown
    - expect: Username and password fields are empty
    - expect: Login button is visible

#### 5.3. Browser Back after logout does not restore the products page

**File:** `apps/saucedemo/specs/AC5-protected-pages-logout.spec.ts`

**Steps:**
  1. Navigate to '/'. Log in with 'standard_user' / 'secret_sauce' to reach '/inventory.html'.
    - expect: Products page is shown
  2. Open the side menu via getByRole('button', { name: 'Open Menu' }) and click '[data-test="logout-sidebar-link"]' to log out.
    - expect: Returns to login page '/'
  3. Press the browser Back button (page.goBack()).
    - expect: Page does NOT show the products grid or '/inventory.html' content
    - expect: URL resolves to '/' (login page)
    - expect: Error alert '[data-test="error"]' is visible with text "Epic sadface: You can only access '/inventory.html' when you are logged in."
    - expect: This confirms the session is fully invalidated and cached pages are not served after logout

#### 5.4. After logout, direct re-navigation to /inventory.html is blocked again

**File:** `apps/saucedemo/specs/AC5-protected-pages-logout.spec.ts`

**Steps:**
  1. Navigate to '/'. Log in with 'standard_user' / 'secret_sauce', then log out via the side menu.
    - expect: Returns to login page '/'
  2. Navigate directly to '/inventory.html' again by URL.
    - expect: Redirected to '/' (login page)
    - expect: Protected-page error message is shown
    - expect: Confirms logout fully revokes access, not just for the Back button case

#### 5.5. Re-login after logout works normally

**File:** `apps/saucedemo/specs/AC5-protected-pages-logout.spec.ts`

**Steps:**
  1. Navigate to '/'. Log in, then log out via the side menu.
    - expect: Returns to login page '/'
  2. Fill in 'standard_user' / 'secret_sauce' again and click Login.
    - expect: Login succeeds and navigates to '/inventory.html'
    - expect: Heading '[data-test="title"]' shows 'Products'
    - expect: Confirms the session state was cleanly reset and a fresh login is possible
