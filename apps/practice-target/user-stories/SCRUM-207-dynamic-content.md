# User Story: SCRUM-207 - Dynamic and Asynchronous Content

## Story Title
As a user, I want loading states, notifications and progress indicators that reflect what is happening in the background so that I know when content is ready or an action failed.

## Story Description
The Dynamic Content page simulates asynchronous behaviour: on-demand loading with a skeleton, a live clock, auto-dismissing toasts, a debounced search, "load more" pagination, a progress bar, an element that appears after a delay and an action that fails every other attempt.

## Application URL
https://custom-test-target-app.vercel.app/dynamic

## Test Credentials
None required. The page is public.

## Acceptance Criteria

### AC1: Load on Demand
- WHEN I click "Load data"
- THEN the button should show "Loading…" and be disabled, and a loading skeleton should appear
- AND after about 1 second the skeleton should disappear and "Fetched content from the mock API." should be shown

### AC2: Toast Notifications
- "Trigger success" should show a toast "Saved successfully."
- "Trigger error" should show a toast "Something went wrong."
- "Trigger info" should show a toast "Heads up: new update available."
- Several toasts can be visible at once, stacked in order
- Each toast should disappear on its own about 3 seconds after it appears

### AC3: Debounced Search and Load More
- The item filter should show "42 matches" initially
- Typing (e.g. "Item 1") should update the count only after typing pauses for about 400 ms (e.g. "Item 1" → "11 matches"). The count should not change on every keystroke
- The catalog list should show 8 items initially
- Each "Load more" click should show "Loading…" and then add 8 more items
- When all 42 items are shown, the "Load more" button should disappear

### AC4: Progress and Delayed Content
- WHEN I click "Start upload"
- THEN the button should show "Uploading…" and be disabled
- AND the progress bar should rise in steps of 10% (about every 200 ms), and its `aria-valuenow` and the "N%" label should match
- AND at 100% the button should return to "Start upload"
- AND the "I appeared after a delay." alert should become visible about 3 seconds after the page loads
- AND the live clock should update every second

### AC5: Flaky Action Handling
- WHEN I click "Run flaky action" the first time
- THEN the button should show "Working…" and then "Failed. Try again." should appear
- WHEN I click it again
- THEN "Succeeded." should appear
- AND the results should keep alternating (odd attempts fail, even attempts succeed) until the page is reloaded

## Business Rules
1. A button that started an async action stays disabled until that action finishes
2. Toasts are informational and dismiss themselves. They need no user action
3. Search runs only after the user stops typing

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Test IDs: `load-data-button`, `load-skeleton`, `loaded-content`, `live-clock`, `toast-success-button`, `toast-error-button`, `toast-info-button`, `toast-stack`, `debounced-search-input`, `debounced-search-count`, `catalog-list`, `load-more-button`, `start-upload-button`, `progress-bar`, `progress-value`, `delayed-element`, `flaky-action-button`, `flaky-action-success`, `flaky-action-error`
- Toast test IDs (`toast-<n>`) use a counter that never resets while the app is open. Locate toasts by text inside `toast-stack`, not by ID
- Rely on Playwright's auto-waiting assertions (`toBeVisible`, `toHaveText`, `toBeHidden`). Never use fixed sleeps. Assertions that wait for a toast to vanish or for the delayed element may need a longer `timeout` option (e.g. 5 s)
- The live clock text depends on locale and time. Assert that it changes, not its value
- The flaky action alternates deterministically. A test must not depend on retries to pass

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
