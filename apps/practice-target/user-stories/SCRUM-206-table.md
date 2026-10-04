# User Story: SCRUM-206 - Users Data Table

## Story Title
As an administrator, I want to search and sort a users table so that I can find the right accounts.

## Story Description
The Table page lists 47 mock users with search, sorting, pagination and selection. (Trimmed scope: search plus column sorting.)

## Application URL
https://custom-test-target-app.vercel.app/table

## Test Credentials
None required.

## Acceptance Criteria

### AC1: Search (happy path)
- GIVEN the table shows "47 results"
- WHEN I type a name or email fragment into the search box
- THEN only matching rows should show and the count should update ("1 result" / "N results")
- WHEN nothing matches, "No matching users." should show; clearing the search should restore all 47

### AC2: Sorting (key behavior)
- WHEN I click a column header (e.g. Name)
- THEN rows should sort ascending by that column (header shows `aria-sort="ascending"`)
- WHEN I click the same header again, they should sort descending

## Business Rules
1. Search matches name or email only
2. Searching resets to page 1

## Technical Notes
- Use Playwright, `page.getByTestId(...)`: `table-search-input`, `table-result-count`, `th-name|email|role|status|joined`, `table-row-<id>`, `table-empty-state`
- Verify sorting by reading the column values and comparing with a sorted copy; data is from a fixed seed (identical each load)
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
