# User Story: SCRUM-102 - Login and Logout

## Story Title
As a customer, I want to log in with my account and log out when I'm done so that only I can shop with my account.

## Story Description
Every page of the shop except the login page requires a logged-in user. The login page accepts a fixed set of demo accounts, all sharing one password, and shows a clear error for each kind of failed attempt. Logging out returns the user to the login page and ends the session.

## Application URL
https://www.saucedemo.com (page: `/`)

## Test Credentials
- Valid user: `standard_user` / `secret_sauce`
- Locked-out user: `locked_out_user` / `secret_sauce`
- Other accepted usernames (listed on the login page): `problem_user`, `performance_glitch_user`, `error_user`, `visual_user`. All use `secret_sauce`

## Acceptance Criteria

### AC1: Successful Login
- GIVEN I am on the login page
- WHEN I enter `standard_user` / `secret_sauce` and click "Login" (or press Enter)
- THEN I should land on `/inventory.html` with the title "Products"
- AND the login page should list the accepted usernames and the shared password

### AC2: Failed Login Messages
- WHEN I submit with an empty username
- THEN I should see "Epic sadface: Username is required"
- WHEN I submit a username with an empty password
- THEN I should see "Epic sadface: Password is required"
- WHEN I submit a wrong username or password
- THEN I should see "Epic sadface: Username and password do not match any user in this service"
- AND in every case I should stay on the login page with the fields marked as in error

### AC3: Locked-out User
- WHEN I log in as `locked_out_user` / `secret_sauce`
- THEN I should see "Epic sadface: Sorry, this user has been locked out."
- AND I should stay on the login page

### AC4: Error Message Dismissal
- GIVEN a login error is shown
- WHEN I click the error's close (X) button
- THEN the error message and the field error markers should disappear

### AC5: Protected Pages and Logout
- GIVEN I am not logged in
- WHEN I open `/inventory.html` directly
- THEN I should be sent to the login page with "Epic sadface: You can only access '/inventory.html' when you are logged in."
- GIVEN I am logged in
- WHEN I choose "Logout" from the menu
- THEN I should return to the login page
- AND pressing the browser Back button should not show the products page again (the protected-page error appears instead)

## Business Rules
1. All accounts share the password `secret_sauce`. Usernames and passwords are case-sensitive
2. A locked-out account can never log in
3. Every page except `/` requires a logged-in user
4. Logout ends the session and empties the cart

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Locators use `data-test` attributes: `username`, `password`, `login-button`, `error`, `error-button` (the X), `login-credentials`, `login-password`, `logout-sidebar-link`
- The SauceDemo seed (`tests/saucedemo/seed.spec.ts`) already logs in. Tests for this story are about the login itself, so they should start from `page.goto('/')` in their own fresh context instead of repeating the seed's login in `beforeEach`
- Open the menu with the "Open Menu" button (`getByRole('button', { name: 'Open Menu' })`). Clicking `[data-test="open-menu"]` times out because the button sits on top of that image
- Other users (`problem_user`, `error_user`, `visual_user`, `performance_glitch_user`) have deliberate defects elsewhere in the shop. This story only checks that they can log in; their defects are out of scope

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
