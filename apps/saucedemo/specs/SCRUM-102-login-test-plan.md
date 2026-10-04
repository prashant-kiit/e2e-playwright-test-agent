# SCRUM-102: Login and Logout - Test Plan

## Application Overview

SauceDemo (https://www.saucedemo.com) login and logout test plan for user story SCRUM-102. Covers successful authentication (AC1), validation/negative login scenarios (AC2), the locked-out user (AC3), error-message dismissal (AC4), and protected-page/logout/back-navigation behavior (AC5).

Environment notes:
- baseURL: https://www.saucedemo.com
- All tests in this story start from a FRESH, logged-out context via `page.goto('/')`. Do NOT reuse the seed login in beforeEach for this story's specs; the seed is only used by planner_setup_page to initialize the test environment.
- Document <title> stays "Swag Labs" on every page (login, inventory). The on-page heading ".title" shows "Products" on the inventory page - assertions about "landing on the Products page" must check the visible heading text/element, not document.title.
- Valid credentials: standard_user / secret_sauce. Locked out: locked_out_user / secret_sauce. Other accepted usernames (login succeeds; app defects on those pages are out of scope for this story): problem_user, performance_glitch_user, error_user, visual_user - all share password secret_sauce.

Stable locators (data-test attributes, confirmed live):
- Username field: `[data-test="username"]`
- Password field: `[data-test="password"]`
- Login button: `[data-test="login-button"]`
- Error banner container: `[data-test="error"]` (role=alert)
- Error dismiss (X) button: `[data-test="error-button"]`
- Accepted usernames list text: `[data-test="login-credentials"]`
- Shared password text: `[data-test="login-password"]`
- Logout link in side menu: `[data-test="logout-sidebar-link"]` (rendered as an `<a>` with text "Logout")
- Open side menu: use `page.getByRole('button', { name: 'Open Menu' })` - clicking `[data-test="open-menu"]` directly times out because the visual button covers it, and a raw JS click leaves menu items `aria-hidden`.
- Close side menu: `page.getByRole('button', { name: 'Close Menu' })`
- Inventory page heading: text "Products" inside `.title` (visible heading, not document.title)

Confirmed exact behaviors from live exploration (2026-10-04):
- Empty username + empty password -> error text exactly: "Epic sadface: Username is required"
- Any username + empty password -> error text exactly: "Epic sadface: Password is required"
- Non-matching username/password combo -> error text exactly: "Epic sadface: Username and password do not match any user in this service"
- Username match is case-sensitive: "Standard_User" / secret_sauce produces the "do not match" error, not success.
- locked_out_user / secret_sauce -> error text exactly: "Epic sadface: Sorry, this user has been locked out."
- Direct/forced navigation to /inventory.html while logged out -> browser is redirected to "/" and shows error text exactly: "Epic sadface: You can only access '/inventory.html' when you are logged in."
- On any validation error, BOTH the username and password `<input>` elements receive an additional CSS class `error` (full className becomes "input_error form_input error"); the static class `input_error` is always present regardless of error state, so assertions should check specifically for the `error` class token, not just `input_error`.
- Clicking the error dismiss (X) button removes the error alert and the `error` class from both fields, but does NOT clear the text the user already typed into username/password.
- After Logout (via side menu "Logout" link), the app returns to "/" with a blank login form. Pressing the browser Back button afterwards does NOT restore the product listing - the browser is redirected back to "/" showing the same protected-page error as direct navigation, confirming no cached authenticated view is served.
- Successful login (via clicking Login, or via pressing Enter in the password field) navigates to /inventory.html and renders the product grid with heading "Products".
- problem_user / secret_sauce was verified to log in successfully (defects on that user's catalog page, if any, are out of scope for this story).

## Test Scenarios

### 1. AC1 - Successful Login

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 1.1. Standard user logs in successfully via Login button click

**File:** `apps/saucedemo/tests/login/AC1-successful-login.spec.ts`

**Steps:**
  1. Navigate to '/' (fresh, logged-out context)
    - expect: Login page is displayed with empty Username and Password fields
    - expect: Login button [data-test="login-button"] is visible and enabled
  2. Fill [data-test="username"] with 'standard_user'
    - expect: Username field shows 'standard_user'
  3. Fill [data-test="password"] with 'secret_sauce'
    - expect: Password field shows masked value (input type=password)
  4. Click [data-test="login-button"]
    - expect: Browser navigates to /inventory.html
    - expect: The products page heading '.title' displays text 'Products'
    - expect: No error alert ([data-test="error"]) is present
    - expect: At least one product card (e.g. 'Sauce Labs Backpack') is visible

#### 1.2. Standard user logs in successfully by pressing Enter in the password field

**File:** `apps/saucedemo/tests/login/AC1-successful-login.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page is displayed
  2. Fill [data-test="username"] with 'standard_user'
    - expect: Username field shows 'standard_user'
  3. Fill [data-test="password"] with 'secret_sauce' and press Enter (do not click the Login button)
    - expect: Form submits the same as a button click
    - expect: Browser navigates to /inventory.html
    - expect: Page heading shows 'Products'

#### 1.3. Login page displays the accepted usernames list and shared password hint

**File:** `apps/saucedemo/tests/login/AC1-successful-login.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page is displayed
  2. Read text content of [data-test="login-credentials"]
    - expect: Text contains heading 'Accepted usernames are:' followed by: standard_user, locked_out_user, problem_user, performance_glitch_user, error_user, visual_user
  3. Read text content of [data-test="login-password"]
    - expect: Text contains heading 'Password for all users:' followed by 'secret_sauce'

#### 1.4. Each additional accepted username can log in with the shared password (data-driven)

**File:** `apps/saucedemo/tests/login/AC1-successful-login.spec.ts`

**Steps:**
  1. For each username in ['problem_user', 'performance_glitch_user', 'error_user', 'visual_user']: navigate to '/' in a fresh context, fill [data-test="username"] with the username and [data-test="password"] with 'secret_sauce', click [data-test="login-button"]
    - expect: For every username in the list, the browser navigates to /inventory.html
    - expect: No login error alert is shown
    - expect: Only cosmetic/functional defects on the resulting catalog page are out of scope for this assertion - the test only checks that authentication itself succeeds (URL + absence of login error)

#### 1.5. Password field masks input characters

**File:** `apps/saucedemo/tests/login/AC1-successful-login.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page is displayed
  2. Fill [data-test="password"] with 'secret_sauce'
    - expect: The input element's type attribute is 'password' so the value is visually masked (not plain text) in the UI

### 2. AC2 - Failed Login Messages

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 2.1. Submitting with both username and password empty shows 'Username is required'

**File:** `apps/saucedemo/tests/login/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page displayed, both fields empty
  2. Click [data-test="login-button"] without filling any field
    - expect: URL remains '/' (still on login page)
    - expect: [data-test="error"] alert is visible with text exactly 'Epic sadface: Username is required'
    - expect: [data-test="username"] and [data-test="password"] both carry the CSS class 'error'

#### 2.2. Submitting with username filled and password empty shows 'Password is required'

**File:** `apps/saucedemo/tests/login/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page displayed
  2. Fill [data-test="username"] with 'standard_user', leave password empty, click [data-test="login-button"]
    - expect: URL remains '/'
    - expect: Error alert text is exactly 'Epic sadface: Password is required'
    - expect: Username field retains 'standard_user'
    - expect: Both username and password fields carry the CSS class 'error'

#### 2.3. Submitting with username empty and password filled still shows 'Username is required'

**File:** `apps/saucedemo/tests/login/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page displayed
  2. Leave username empty, fill [data-test="password"] with 'secret_sauce', click [data-test="login-button"]
    - expect: URL remains '/'
    - expect: Error alert text is exactly 'Epic sadface: Username is required' (username validation takes precedence over password validation)
    - expect: Password field retains the typed value

#### 2.4. Wrong username and wrong password shows the generic mismatch error

**File:** `apps/saucedemo/tests/login/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page displayed
  2. Fill username with 'invalid_user' and password with 'wrong_pass', submit via Enter key in the password field
    - expect: URL remains '/'
    - expect: Error alert text is exactly 'Epic sadface: Username and password do not match any user in this service'
    - expect: Both fields carry the CSS class 'error'

#### 2.5. Valid username with wrong password shows the generic mismatch error

**File:** `apps/saucedemo/tests/login/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page displayed
  2. Fill username with 'standard_user' and password with 'wrong_pass', click [data-test="login-button"]
    - expect: URL remains '/'
    - expect: Error text is exactly 'Epic sadface: Username and password do not match any user in this service'

#### 2.6. Wrong username with the correct shared password shows the generic mismatch error

**File:** `apps/saucedemo/tests/login/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page displayed
  2. Fill username with 'not_a_real_user' and password with 'secret_sauce', click [data-test="login-button"]
    - expect: URL remains '/'
    - expect: Error text is exactly 'Epic sadface: Username and password do not match any user in this service'

#### 2.7. Username match is case-sensitive - 'Standard_User' is rejected

**File:** `apps/saucedemo/tests/login/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page displayed
  2. Fill username with 'Standard_User' (capitalized) and password with 'secret_sauce', submit
    - expect: Login does NOT succeed; URL remains '/'
    - expect: Error text is exactly 'Epic sadface: Username and password do not match any user in this service'
    - expect: Confirms username matching is case-sensitive

#### 2.8. Validation error highlights both username and password fields regardless of error type

**File:** `apps/saucedemo/tests/login/AC2-failed-login-messages.spec.ts`

**Steps:**
  1. Navigate to '/' and submit with empty username/password to trigger 'Username is required'
    - expect: Both [data-test="username"] and [data-test="password"] className contains the token 'error' (in addition to the always-present 'input_error' token)
  2. Repeat for the wrong-credentials mismatch case and the locked_out_user case
    - expect: In every error scenario, both fields carry the 'error' class token, confirming consistent field-level error marking across all AC2/AC3 error types

### 3. AC3 - Locked-out User

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 3.1. Locked-out user sees the lockout error and remains on the login page

**File:** `apps/saucedemo/tests/login/AC3-locked-out-user.spec.ts`

**Steps:**
  1. Navigate to '/'
    - expect: Login page displayed
  2. Fill username with 'locked_out_user' and password with 'secret_sauce', click [data-test="login-button"]
    - expect: URL remains '/' (no navigation to /inventory.html)
    - expect: [data-test="error"] alert text is exactly 'Epic sadface: Sorry, this user has been locked out.'
    - expect: Both username and password fields carry the 'error' CSS class

#### 3.2. Locked-out user cannot access the protected inventory page even via direct navigation

**File:** `apps/saucedemo/tests/login/AC3-locked-out-user.spec.ts`

**Steps:**
  1. Navigate to '/', attempt login with locked_out_user/secret_sauce and observe the lockout error
    - expect: Lockout error shown, user remains unauthenticated
  2. Navigate directly to '/inventory.html'
    - expect: Browser is redirected back to '/'
    - expect: Error alert text is exactly "Epic sadface: You can only access '/inventory.html' when you are logged in." (confirms the failed locked-out attempt did not create a session)

#### 3.3. Locked-out error can be dismissed and the user can retry (and still fails)

**File:** `apps/saucedemo/tests/login/AC3-locked-out-user.spec.ts`

**Steps:**
  1. Navigate to '/', submit locked_out_user/secret_sauce to trigger the lockout error
    - expect: Lockout error visible
  2. Click [data-test="error-button"] to dismiss the error
    - expect: Error alert disappears
    - expect: 'error' CSS class removed from both fields
    - expect: Username/password text values remain in the inputs
  3. Click [data-test="login-button"] again without changing the fields
    - expect: The exact same lockout error reappears: 'Epic sadface: Sorry, this user has been locked out.'
    - expect: User still remains on '/'

### 4. AC4 - Error Message Dismissal

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 4.1. Dismissing the 'Username is required' error clears the alert and field error styling

**File:** `apps/saucedemo/tests/login/AC4-error-dismissal.spec.ts`

**Steps:**
  1. Navigate to '/' and click [data-test="login-button"] with empty fields to trigger 'Username is required'
    - expect: Error alert and field error classes present
  2. Click [data-test="error-button"] (the X icon)
    - expect: [data-test="error"] alert is no longer present in the DOM/visible
    - expect: Neither username nor password field carries the 'error' CSS class any more

#### 4.2. Dismissing the 'Password is required' error clears the alert

**File:** `apps/saucedemo/tests/login/AC4-error-dismissal.spec.ts`

**Steps:**
  1. Navigate to '/', fill username only, submit to trigger 'Password is required'
    - expect: Error alert visible
  2. Click [data-test="error-button"]
    - expect: Error alert disappears
    - expect: Field error classes cleared
    - expect: Username value 'standard_user' (or whatever was typed) is still present in the username field

#### 4.3. Dismissing the credential-mismatch error preserves previously typed field values

**File:** `apps/saucedemo/tests/login/AC4-error-dismissal.spec.ts`

**Steps:**
  1. Navigate to '/', fill username 'bad_user' and password 'bad_pass', submit to trigger the mismatch error
    - expect: Error alert 'Epic sadface: Username and password do not match any user in this service' visible
  2. Click [data-test="error-button"]
    - expect: Error alert disappears
    - expect: Username field value is still 'bad_user'
    - expect: Password field value is still 'bad_pass'
    - expect: Error CSS class removed from both fields

#### 4.4. Dismissing the locked-out error clears the alert and allows editing the form

**File:** `apps/saucedemo/tests/login/AC4-error-dismissal.spec.ts`

**Steps:**
  1. Navigate to '/', submit locked_out_user/secret_sauce to trigger the lockout error
    - expect: Lockout error visible
  2. Click [data-test="error-button"]
    - expect: Error alert disappears, field error classes removed
  3. Clear fields and fill with standard_user/secret_sauce, then submit
    - expect: Login now succeeds and navigates to /inventory.html, confirming the dismissed error did not leave the form in a broken state

#### 4.5. Error alert is not present on a freshly loaded login page

**File:** `apps/saucedemo/tests/login/AC4-error-dismissal.spec.ts`

**Steps:**
  1. Navigate to '/' in a brand-new context (no prior error triggered)
    - expect: [data-test="error"] element is not present/visible
    - expect: Neither field carries the 'error' CSS class
    - expect: This is the baseline negative check that the X button test relies on by contrast

### 5. AC5 - Protected Pages and Logout

**Seed:** `apps/saucedemo/seed.spec.ts`

#### 5.1. Direct navigation to a protected page while logged out redirects to login with the correct error

**File:** `apps/saucedemo/tests/login/AC5-protected-pages-and-logout.spec.ts`

**Steps:**
  1. In a fresh, logged-out context, navigate directly to '/inventory.html'
    - expect: Browser URL is redirected to '/'
    - expect: [data-test="error"] alert text is exactly "Epic sadface: You can only access '/inventory.html' when you are logged in."
    - expect: No product grid/content is rendered - only the login form is visible

#### 5.2. Authenticated user can access the inventory page and sees the product catalog

**File:** `apps/saucedemo/tests/login/AC5-protected-pages-and-logout.spec.ts`

**Steps:**
  1. Navigate to '/', log in with standard_user/secret_sauce
    - expect: Navigated to /inventory.html
    - expect: Page heading '.title' shows 'Products'
    - expect: Product cards are rendered (e.g. 'Sauce Labs Backpack' visible)

#### 5.3. Logout via the side menu returns the user to the login page

**File:** `apps/saucedemo/tests/login/AC5-protected-pages-and-logout.spec.ts`

**Steps:**
  1. Navigate to '/', log in with standard_user/secret_sauce to reach /inventory.html
    - expect: On inventory page
  2. Open the side menu using page.getByRole('button', { name: 'Open Menu' }) (do NOT click [data-test="open-menu"] directly - it is covered by the visual button and will time out)
    - expect: Side menu panel opens showing 'All Items', 'Dynamic Catalog', 'About', 'Logout', 'Reset App State'
  3. Click [data-test="logout-sidebar-link"] (the 'Logout' link)
    - expect: Browser navigates back to '/'
    - expect: A blank login form is displayed (no error alert)
    - expect: No session/cart state is visible

#### 5.4. Browser Back button after logout does not restore the protected product page

**File:** `apps/saucedemo/tests/login/AC5-protected-pages-and-logout.spec.ts`

**Steps:**
  1. Navigate to '/', log in with standard_user/secret_sauce to reach /inventory.html
    - expect: On inventory page, Products heading visible
  2. Open the side menu (getByRole button 'Open Menu') and click [data-test="logout-sidebar-link"] to log out
    - expect: Back on '/' with blank login form
  3. Press the browser Back button (page.goBack())
    - expect: The product catalog is NOT shown (no cached authenticated page is served from history)
    - expect: Browser ends up on '/' displaying the protected-page error: "Epic sadface: You can only access '/inventory.html' when you are logged in."
    - expect: This is the key regression check for this story: logout must truly invalidate the session, not just visually return to login while leaving /inventory.html cached/accessible via history

#### 5.5. Side menu Open/Close controls work correctly around the logout action

**File:** `apps/saucedemo/tests/login/AC5-protected-pages-and-logout.spec.ts`

**Steps:**
  1. Navigate to '/', log in with standard_user/secret_sauce
    - expect: On inventory page
  2. Click getByRole('button', { name: 'Open Menu' })
    - expect: Menu panel becomes visible with 'Logout' link visible and not aria-hidden
  3. Click getByRole('button', { name: 'Close Menu' }) without logging out
    - expect: Menu panel closes; product grid remains visible and the user is still logged in (re-opening the menu still shows Logout, confirming session persisted through an open/close cycle)
  4. Re-open the menu and click [data-test="logout-sidebar-link"]
    - expect: User is logged out and returned to '/'

#### 5.6. Directly re-navigating to '/inventory.html' immediately after logout still shows the protected-page error

**File:** `apps/saucedemo/tests/login/AC5-protected-pages-and-logout.spec.ts`

**Steps:**
  1. Navigate to '/', log in with standard_user/secret_sauce, then log out via the side menu
    - expect: Back on '/' login form
  2. Navigate directly (page.goto) to '/inventory.html' again
    - expect: Redirected to '/'
    - expect: Error alert exactly "Epic sadface: You can only access '/inventory.html' when you are logged in." is shown, confirming no residual session/cookie allows access post-logout
