# User Story: SCRUM-207 - Dynamic and Asynchronous Content

## Story Title
As a user, I want loading states and notifications that reflect background work so that I know when things are ready.

## Story Description
The Dynamic Content page simulates async behaviour. (Trimmed scope: on-demand loading plus auto-dismissing toasts.)

## Application URL
https://custom-test-target-app.vercel.app/dynamic

## Test Credentials
None required.

## Acceptance Criteria

### AC1: Load on Demand (happy path)
- WHEN I click "Load data"
- THEN the button should show "Loading…" and be disabled and a skeleton should appear
- AND after about 1 s the skeleton should disappear and "Fetched content from the mock API." should show

### AC2: Toast Notifications (key behavior)
- WHEN I click "Trigger success" / "Trigger error" / "Trigger info"
- THEN a toast should appear with "Saved successfully." / "Something went wrong." / "Heads up: new update available."
- AND each toast should disappear on its own about 3 s later

## Business Rules
1. A button that started an async action stays disabled until it finishes
2. Toasts dismiss themselves

## Technical Notes
- Use Playwright, `page.getByTestId(...)`: `load-data-button`, `load-skeleton`, `loaded-content`, `toast-success-button`, `toast-error-button`, `toast-info-button`, `toast-stack`
- Locate toasts by their text inside `toast-stack` (their ids keep incrementing). Use auto-waiting assertions (a toast vanishing may need a longer timeout, e.g. 5 s); never fixed sleeps
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
