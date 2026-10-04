# User Story: SCRUM-202 - Account Sign-up Form

## Story Title
As a new visitor, I want to fill in a sign-up form with clear validation so that I can create an account without guessing what is wrong.

## Story Description
The Forms page holds a "Create account" form that uses every common input type: text, email, password with a show/hide toggle, number, textarea, select, radio group, checkbox group, range slider, date, file upload and a terms checkbox. Validation runs on the client when the form is submitted. A valid submission is simulated (about 800 ms) and ends with a success alert. A Reset button restores the defaults.

## Application URL
https://custom-test-target-app.vercel.app/forms

## Test Credentials
None required. The page is public.

## Acceptance Criteria

### AC1: Successful Submission
- GIVEN I am on the Forms page
- WHEN I fill in Full name, a valid Email, a Password of at least 8 characters, select a Country, accept the terms and click "Create account"
- THEN the button should show "Submitting…" and be disabled while the request is pending
- AND I should then see the alert "Submitted successfully! Registered <Full name> (<Email>)."

### AC2: Mandatory Field Validation
- GIVEN I am on the Forms page
- WHEN I click "Create account" with the form empty
- THEN I should see these field errors:
  - Full name: "Full name is required."
  - Email: "Email is required."
  - Password: "Password is required."
  - Country: "Please select a country."
  - Terms: "You must accept the terms to continue."
- AND the invalid inputs should be marked `aria-invalid="true"`
- AND no success alert should appear

### AC3: Format and Range Validation
- WHEN I enter an email without a valid `name@domain.tld` shape
- THEN I should see "Enter a valid email address."
- WHEN I enter a password shorter than 8 characters
- THEN I should see "Password must be at least 8 characters."
- WHEN I enter an Age below 18 or above 120
- THEN I should see "Age must be between 18 and 120."
- AND leaving Age empty should be allowed (it is optional)
- AND whitespace-only Full name should count as empty

### AC4: Input Controls
- The password "Show" button should reveal the password (input type becomes `text`, button reads "Hide") and "Hide" should mask it again
- Plan radios (Basic, Pro, Enterprise) should allow exactly one choice, with Basic selected by default
- Interests checkboxes (Automation, Design, Performance, Accessibility, Security) should allow any combination
- The Experience slider (1–5, default 3) should update its label "Experience level: N"
- Choosing a file in "Resume (mock upload)" should show "Selected: <file name>"
- The Country select should list United States, United Kingdom, India, Germany, Japan and Brazil

### AC5: Reset
- GIVEN I have filled in fields and/or triggered errors or the success alert
- WHEN I click "Reset"
- THEN every field should return to its default (empty text fields, Basic plan, no interests, experience 3, terms unchecked)
- AND all error messages and the success alert should disappear

## Business Rules
1. Full name, Email, Password, Country and Terms acceptance are mandatory
2. Age, Bio, Plan, Interests, Experience, Start date and Resume are optional
3. Errors appear only after a submit attempt, and every error is shown at once
4. Nothing is sent to a server. The submission is simulated

## Technical Notes
- Use Playwright for test automation
- Test across Chrome, Firefox, Safari and a mobile viewport
- Every control has a `data-testid` (e.g. `input-full-name`, `input-email`, `input-password`, `toggle-password-visibility`, `input-age`, `input-bio`, `select-country`, `radio-plan-pro`, `checkbox-interest-design`, `input-experience-range`, `input-start-date`, `input-resume-upload`, `resume-file-name`, `checkbox-accept-terms`, `submit-form-button`, `reset-form-button`, `form-success-alert`, `error-email` …). Prefer `page.getByTestId()`
- The form uses `noValidate`, so the browser's built-in validation bubbles never appear. Assert on the app's own error messages
- Use `setInputFiles` with an in-memory buffer for the upload, so no fixture file is needed
- Wait on the success alert, not on a fixed timeout

## Definition of Done
- [ ] All acceptance criteria have test cases
- [ ] Manual exploratory testing completed
- [ ] Automated test scripts created and passing
- [ ] Test results documented
- [ ] Bugs logged for any failures
- [ ] Code committed to repository
