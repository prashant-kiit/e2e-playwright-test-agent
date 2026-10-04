# User Story: SCRUM-204 - Modal Dialogs

## Story Title
As a user, I want dialogs that confirm actions and collect input so that I don't make mistakes.

## Story Description
The Modals page shows several dialog patterns. (Trimmed scope: the confirm dialog plus the form modal.)

## Application URL
https://custom-test-target-app.vercel.app/modals

## Test Credentials
None required.

## Acceptance Criteria

### AC1: Confirm Dialog (happy path)
- WHEN I click "Delete item"
- THEN a dialog titled "Delete item?" should open with Cancel and Delete
- WHEN I click "Delete" the dialog should close and "Last action: deleted" should appear
- WHEN I reopen it and click "Cancel" it should close and "Last action: cancelled" should appear

### AC2: Form Modal (key behavior)
- WHEN I click "Add contact", enter a name and click "Save"
- THEN the dialog should close and "Added contact: <name>" should appear
- WHEN I reopen it and click "Save" with the name empty, the dialog should stay open (the field is required)

## Business Rules
1. Cancelling a dialog never changes data

## Technical Notes
- Use Playwright, `page.getByTestId(...)`: `open-confirm-modal`, `confirm-modal`, `confirm-modal-cancel`, `confirm-modal-confirm`, `confirm-result`, `open-form-modal`, `form-modal`, `form-modal-name-input`, `form-modal-submit`, `form-modal-result`
- Dialogs expose `role="dialog"`; they can also be found with `getByRole('dialog', { name: '<title>' })`
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
