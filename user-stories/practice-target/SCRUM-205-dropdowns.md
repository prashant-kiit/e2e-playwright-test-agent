# User Story: SCRUM-205 - Dropdown and Selection Controls

## Story Title
As a user, I want to pick one or more values from lists, including searching a long list, so that I can make selections quickly.

## Story Description
The Dropdowns page has five selection controls: a native single select, a native multi-select, a custom listbox (role picker), a searchable autocomplete (fruit) and a multi-select that shows the chosen values as removable chips (skills).

## Application URL
https://custom-test-target-app.vercel.app/dropdowns

## Test Credentials
None required. The page is public.

## Acceptance Criteria

### AC1: Native Selects
- The single select should show the disabled placeholder "Choose one…" by default and offer Option A, Option B and Option C
- Selecting an option should make it the selected value
- The multi-select should list Apple, Banana, Cherry, Date and Elderberry and allow several values to be selected at once

### AC2: Custom Listbox
- The trigger should read "Select a role…" with `aria-expanded="false"`
- Clicking the trigger should open a listbox with Admin, Editor, Viewer and Owner, and set `aria-expanded="true"`
- Clicking an option should close the menu, show the option on the trigger and mark it `aria-selected="true"` the next time the menu opens
- Clicking outside the open menu should close it without changing the selection

### AC3: Searchable Autocomplete
- Focusing the "Search fruit…" input should open a list of all 8 fruits (Apple, Banana, Cherry, Date, Elderberry, Fig, Grape, Honeydew)
- Typing should filter the list case-insensitively by substring (e.g. "an" shows only Banana)
- Clicking a suggestion should fill the input, close the list and show "Picked: <fruit>"
- Typing again after picking should clear the "Picked" text
- When nothing matches, no list should be shown

### AC4: Multi-select with Chips
- The trigger should read "Select skills…" until something is chosen, then "<N> selected"
- The menu should list JavaScript, TypeScript, Python, Go, Rust and SQL. Clicking an option should toggle it (☐ / ☑) and keep the menu open
- Each selected skill should appear as a chip with a "×" remove button (accessible name "Remove <skill>")
- Removing a chip should deselect the skill and update the count. When the last chip goes, the trigger should read "Select skills…" again
- Clicking outside should close the menu and keep the selection

### AC5: Keyboard and Accessibility
- Custom menus should use `role="listbox"` with `role="option"` items, and the multi-select menu should set `aria-multiselectable="true"`
- The native selects should be operable with the keyboard

## Business Rules
1. The custom listbox allows exactly one role
2. The autocomplete only accepts a value picked from the list ("Picked" appears only after a pick)
3. The chip list and the multi-select menu always stay in sync

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Test IDs: `native-select`, `native-multi-select`, `custom-select`, `custom-select-trigger`, `custom-select-menu`, `custom-select-option-<role>`, `autocomplete-input`, `autocomplete-menu`, `autocomplete-option-<fruit>`, `autocomplete-picked`, `multi-select-trigger`, `multi-select-menu`, `multi-select-option-<skill>`, `multi-select-chip-list`, `chip-<skill>`, `chip-remove-<skill>` (all lower-case)
- Use `selectOption()` for native selects only. The custom controls are clicked
- To close a menu by clicking outside, click a neutral element such as the page heading

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
