# User Story: SCRUM-102 - Login

## Story Title
As a customer, I want to log in so that I can shop, and see a clear error when my details are wrong.

## Story Description
The login page accepts the demo account and shows an error for bad credentials. (Trimmed scope: successful login plus the wrong-credentials error.)

## Application URL
https://www.saucedemo.com (page: `/`)

## Test Credentials
- Username: `standard_user`
- Password: `secret_sauce`

## Acceptance Criteria

### AC1: Successful Login (happy path)
- GIVEN I am on the login page
- WHEN I enter `standard_user` / `secret_sauce` and click Login
- THEN I should land on `/inventory.html` with the title "Products"

### AC2: Wrong Credentials (key negative)
- WHEN I submit a wrong username or password
- THEN I should see "Epic sadface: Username and password do not match any user in this service"
- AND I should stay on the login page

## Business Rules
1. Credentials are case-sensitive
2. Every page except `/` requires a logged-in user

## Technical Notes
- Use Playwright. Locators use `data-test` attributes: `username`, `password`, `login-button`, `error`, `title`
- This story is about login itself, so tests start from `page.goto('/')` (don't reuse the seed's logged-in state)
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
