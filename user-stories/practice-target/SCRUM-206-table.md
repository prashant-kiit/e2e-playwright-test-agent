# User Story: SCRUM-206 - Users Data Table

## Story Title
As an administrator, I want to search, sort, page through and select users in a table so that I can find and act on the right accounts.

## Story Description
The Table page lists 47 mock users with Name, Email, Role, Status and Joined date. The data is generated from a fixed seed, so it is identical on every load. The table supports text search, column sorting, a page-size selector, pagination and row selection with a bulk-action bar.

## Application URL
https://custom-test-target-app.vercel.app/table

## Test Credentials
None required. The page is public.

## Acceptance Criteria

### AC1: Initial State
- GIVEN I open the Table page
- THEN I should see "47 results"
- AND 10 rows on page 1, sorted by Name ascending (the Name header shows ▲ and `aria-sort="ascending"`)
- AND pagination buttons Prev (disabled), 1–5 and Next
- AND each Status cell should show a badge: active, invited or suspended

### AC2: Search
- WHEN I type in "Search name or email…"
- THEN only users whose name or email contains the text (case-insensitive) should be shown
- AND the result count should update ("1 result" singular, "N results" plural)
- AND the table should jump back to page 1
- WHEN nothing matches
- THEN "No matching users." should be shown and the count should read "0 results"
- AND clearing the search should restore all 47 results

### AC3: Sorting
- Clicking a column header (Name, Email, Role, Status, Joined) should sort ascending by that column
- Clicking the same header again should switch to descending (▼, `aria-sort="descending"`)
- Only the active column should show an arrow. The other columns should have `aria-sort="none"`

### AC4: Pagination and Page Size
- Next/Prev and the numbered buttons should change the page. The current page button should have `aria-current="true"`
- Next should be disabled on the last page (page 5 at 10 rows per page holds 7 rows)
- Changing "Rows per page" to 5 or 20 should resize the pages (10 or 3 pages) and return to page 1

### AC5: Row Selection
- Checking a row should show the bulk bar "1 row selected", and more rows should show "N rows selected"
- The header checkbox should select or deselect every row on the current page only
- The header checkbox should be checked only when every row on the current page is selected
- Selections should persist when I change page
- "Clear selection" should deselect everything and hide the bulk bar

## Business Rules
1. Search matches name or email only, never role or status
2. Searching or changing the page size always resets to page 1
3. Select-all applies to the visible page, not to all results

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Test IDs: `users-table`, `table-search-input`, `table-page-size-select`, `table-result-count`, `th-name|email|role|status|joined`, `table-row-<id>`, `row-checkbox-<id>`, `status-badge-<id>`, `select-all-checkbox`, `bulk-action-bar`, `clear-selection-button`, `table-empty-state`, `table-pagination`, `pagination-prev`, `pagination-next`, `pagination-page-<n>`
- Row IDs (1–47) are stable, but don't hard-code which row appears first. Verify sorting by reading the column values and comparing them with a sorted copy
- Search filters on every keystroke (no debounce)

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
