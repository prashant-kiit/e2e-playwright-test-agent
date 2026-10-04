# User Story: SCRUM-202 - Account Sign-up Form

## Story Title
As a new visitor, I want to fill in a sign-up form with clear validation so that I know what's wrong.

## Story Description
The Forms page has a "Create account" form with client-side validation and a simulated async submit. (Trimmed scope: a valid submission plus mandatory-field validation.)

## Application URL
https://custom-test-target-app.vercel.app/forms

## Test Credentials
None required.

## Acceptance Criteria

### AC1: Successful Submission (happy path)
- WHEN I fill Full name, a valid Email, a Password of at least 8 characters, select a Country, accept the terms and click "Create account"
- THEN the button should show "Submitting…" while pending
- AND I should then see "Submitted successfully! Registered <Full name> (<Email>)."

### AC2: Mandatory Field Validation (key negative)
- WHEN I click "Create account" with the form empty
- THEN I should see: "Full name is required.", "Email is required.", "Password is required.", "Please select a country." and "You must accept the terms to continue."
- AND no success alert should appear

## Business Rules
1. Full name, Email, Password, Country and Terms are mandatory; the other fields are optional
2. Errors appear only after a submit attempt

## Technical Notes
- Use Playwright, `page.getByTestId(...)`: `input-full-name`, `input-email`, `input-password`, `select-country`, `checkbox-accept-terms`, `submit-form-button`, `form-success-alert`, `error-full-name`, `error-email`, `error-password`, `error-country`, `error-accept-terms`
- The form uses `noValidate`; assert on the app's own error messages, not browser bubbles
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
