# User Story: SCRUM-205 - Dropdown and Selection Controls

## Story Title
As a user, I want to pick values from lists, including searching a long list, so that I can select quickly.

## Story Description
The Dropdowns page has several selection controls. (Trimmed scope: the custom listbox plus the searchable autocomplete.)

## Application URL
https://custom-test-target-app.vercel.app/dropdowns

## Test Credentials
None required.

## Acceptance Criteria

### AC1: Custom Listbox (happy path)
- The trigger should read "Select a role…" with `aria-expanded="false"`
- WHEN I click it, a listbox with Admin, Editor, Viewer, Owner should open (`aria-expanded="true"`)
- WHEN I click an option, the menu should close and the trigger should show that option

### AC2: Searchable Autocomplete (key behavior)
- WHEN I focus the "Search fruit…" input, a list of fruits should appear
- WHEN I type "an", the list should filter to Banana (case-insensitive substring)
- WHEN I click a suggestion, the input should fill, the list should close and "Picked: <fruit>" should show

## Business Rules
1. The custom listbox allows exactly one role
2. "Picked" appears only after a value is chosen from the list

## Technical Notes
- Use Playwright, `page.getByTestId(...)`: `custom-select-trigger`, `custom-select-menu`, `custom-select-option-<role>`, `autocomplete-input`, `autocomplete-menu`, `autocomplete-option-<fruit>`, `autocomplete-picked` (all lower-case)
- To close a menu, click a neutral element such as the page heading
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
