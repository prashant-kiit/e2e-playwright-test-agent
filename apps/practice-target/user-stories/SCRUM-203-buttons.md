# User Story: SCRUM-203 - Button Interactions

## Story Title
As a user, I want buttons to give immediate, accurate feedback for every kind of interaction so that I always know what my click did.

## Story Description
The Buttons page demonstrates the button patterns used across the product: a click counter, a button that can be disabled, an async action with a loading state, a toggle, a double-click action, an exclusive button group and a right-click context menu.

## Application URL
https://custom-test-target-app.vercel.app/buttons

## Test Credentials
None required. The page is public.

## Acceptance Criteria

### AC1: Click Counter
- GIVEN I am on the Buttons page
- THEN the counter button should read "Clicked 0 times"
- WHEN I click it once
- THEN it should read "Clicked 1 time" (singular)
- WHEN I click it again
- THEN it should read "Clicked 2 times"

### AC2: Disabled and Loading States
- WHEN I check "Disable the button below"
- THEN the "Submit" button should be disabled, and enabled again when I uncheck it
- WHEN I click "Run action"
- THEN the button should show "Processing…" and be disabled
- AND after about 1.2 seconds it should return to "Run action" and "Action completed." should appear

### AC3: Toggle and Button Group
- The like button should start as "♡ Like" with `aria-pressed="false"`
- Clicking it should switch to "♥ Liked" with `aria-pressed="true"`, and clicking again should switch back
- In the Size group (SM, MD, LG), MD should be pressed by default
- Clicking another size should press it and un-press the others (only one pressed at a time)

### AC4: Double-click Action
- The hint should start as "Double-clicked 0 times"
- A single click should not change the count
- Each double-click should add one ("Double-clicked 1 time", "Double-clicked 2 times")

### AC5: Right-click Context Menu
- WHEN I right-click inside the "Right-click inside this box" area
- THEN a context menu with the items Copy, Paste and Delete should appear at the pointer
- WHEN I click anywhere on the page
- THEN the menu should close

## Business Rules
1. A disabled button must not respond to clicks
2. An async action can't be started again while it is still running
3. Exactly one size is selected at any time
4. Menu items are placeholders and have no action of their own

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Test IDs: `counter-button`, `checkbox-disable-target`, `disableable-button`, `async-action-button`, `async-action-result`, `like-toggle-button`, `double-click-button`, `double-click-count`, `button-group-size`, `size-button-sm|md|lg`, `context-menu-target`, `context-menu`, `context-menu-item-copy|paste|delete`
- Use `dblclick()` for the double-click and `click({ button: 'right' })` for the context menu
- Right-click and double-click have no touch equivalent. On the `practice-target-mobile-chrome` project these may need `test.skip` with a reason, which should be recorded in the report
- Wait on the result text, not a fixed timeout

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
