# User Story: SCRUM-204 - Modal Dialogs

## Story Title
As a user, I want dialogs that ask for confirmation, collect input and block me only when necessary so that I don't lose work or miss important messages.

## Story Description
The Modals page shows four dialog patterns: a destructive-action confirm dialog, a form modal, nested parent/child modals and a non-dismissible alert. Every dialog is rendered with `role="dialog"` and `aria-modal="true"` over an overlay. Clicking the overlay closes every dialog except the alert.

## Application URL
https://custom-test-target-app.vercel.app/modals

## Test Credentials
None required. The page is public.

## Acceptance Criteria

### AC1: Confirm Dialog
- WHEN I click "Delete item"
- THEN a dialog titled "Delete item?" should open with the text "This action cannot be undone." and the buttons Cancel and Delete
- WHEN I click "Delete"
- THEN the dialog should close and "Last action: deleted" should appear
- WHEN I reopen it and click "Cancel"
- THEN the dialog should close and "Last action: cancelled" should appear
- WHEN I reopen it and click the overlay outside the dialog
- THEN the dialog should close and the last action should stay unchanged

### AC2: Form Modal
- WHEN I click "Add contact"
- THEN a dialog titled "Add contact" should open with a required Name field and the buttons Cancel and Save
- WHEN I enter a name and click "Save" (or press Enter)
- THEN the dialog should close and "Added contact: <name>" should appear
- WHEN I click "Save" with the Name empty
- THEN the dialog should stay open (the field is `required`)
- WHEN I click "Cancel"
- THEN the dialog should close without adding a contact
- AND reopening the dialog after a save should show an empty Name field

### AC3: Nested Modals
- WHEN I click "Open parent modal"
- THEN the "Parent modal" dialog should open
- WHEN I click "Open child modal"
- THEN the "Child modal" dialog should open on top while the parent stays open
- WHEN I click "Close all"
- THEN both dialogs should close
- AND the parent's "Close" button should close the parent when no child is open

### AC4: Non-dismissible Alert
- WHEN I click "Trigger important alert"
- THEN the "Action required" dialog should open with "You must acknowledge this message before continuing."
- WHEN I click the overlay outside the dialog
- THEN the dialog should stay open
- WHEN I click "Acknowledge"
- THEN the dialog should close

### AC5: Accessibility
- Every open dialog should expose `role="dialog"`, `aria-modal="true"` and an accessible name from its heading (`aria-labelledby`)
- Dialogs should be locatable with `page.getByRole('dialog', { name: '<title>' })`

## Business Rules
1. Destructive actions need explicit confirmation
2. Cancelling a dialog never changes data
3. A non-dismissible alert can only be closed by its own button
4. Closing the child modal with "Close all" also closes its parent

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Test IDs: `open-confirm-modal`, `confirm-modal`, `confirm-modal-cancel`, `confirm-modal-confirm`, `confirm-result`, `open-form-modal`, `form-modal`, `form-modal-name-input`, `form-modal-cancel`, `form-modal-submit`, `form-modal-result`, `open-parent-modal`, `parent-modal`, `parent-modal-close`, `open-child-modal`, `child-modal`, `child-modal-close-all`, `open-alert-modal`, `alert-modal`, `alert-modal-acknowledge`. Each overlay has the test ID `<modal-test-id>-overlay`
- To click the overlay and not the dialog, click the overlay at a position outside the dialog box (e.g. `overlay.click({ position: { x: 5, y: 5 } })`)
- The Escape key is not wired to close dialogs. If exploration confirms this, record it as an observation, not a test failure

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
