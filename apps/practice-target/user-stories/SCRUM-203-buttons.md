# User Story: SCRUM-203 - Button Interactions

## Story Title
As a user, I want buttons to give accurate feedback so that I know what my click did.

## Story Description
The Buttons page demonstrates several button patterns. (Trimmed scope: the click counter plus the async loading state.)

## Application URL
https://custom-test-target-app.vercel.app/buttons

## Test Credentials
None required.

## Acceptance Criteria

### AC1: Click Counter (happy path)
- THEN the counter button should read "Clicked 0 times"
- WHEN I click it once it should read "Clicked 1 time" (singular)
- WHEN I click it again it should read "Clicked 2 times"

### AC2: Async Loading State (key behavior)
- WHEN I click "Run action"
- THEN the button should show "Processing…" and be disabled
- AND after about 1.2 s it should return to "Run action" and "Action completed." should appear

## Business Rules
1. An async action can't be started again while it's still running

## Technical Notes
- Use Playwright, `page.getByTestId(...)`: `counter-button`, `async-action-button`, `async-action-result`
- Wait on the result text/state, not a fixed timeout
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
