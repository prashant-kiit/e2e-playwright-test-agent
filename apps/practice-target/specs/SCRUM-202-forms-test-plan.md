# SCRUM-202 Account Sign-up Form Test Plan

## Application Overview

The Playwright Practice Target app's "Forms" page (/forms) hosts an "Create account" sign-up form (data-testid="signup-form") used to exercise form validation and async-submit patterns. The form has mandatory fields (Full name, Email, Password, Country, Accept-terms checkbox) and several optional fields (Age, Bio, Plan radio group, Interests checkboxes, Experience range slider, Preferred start date, Resume upload). The form sets the native `noValidate` attribute, so all validation is handled by custom JS and rendered into `error-*` testid elements only after a submit attempt is made (no live/on-blur validation). On a successful submit the submit button (`submit-form-button`) becomes disabled and its text changes to "Submitting…" for roughly 700-800ms (simulated async delay), then re-enables showing "Create account" again, and a success alert (`form-success-alert`) renders the text "Submitted successfully! Registered &lt;Full name&gt; (&lt;Email&gt;)." Country is a native HTML `<select>` element (not a custom combobox/listbox). This plan covers AC1 (happy path), AC2 (empty-submit mandatory validation), and additional boundary/format validations and UI-state behaviors that were directly observed on the live app (password min-length boundary, email format validation, no-errors-before-first-submit, errors persist until resubmit, button disabled during submit, errors clear on success).

## Test Scenarios

### 1. Happy Path - Successful Submission

**Seed:** `apps/practice-target/seed.spec.ts`

#### 1.1. Submitting the form with all mandatory fields filled shows Submitting state then success alert

**File:** `apps/practice-target/tests/forms/happy-path.spec.ts`

**Steps:**
  1. Navigate to /forms (base URL + /forms). Assume a fresh page load with the sign-up form in its default blank state.
    - expect: Forms page loads with heading 'Create account' visible and signup-form present
  2. Assert the initial state of the form before any interaction: no elements matching error-full-name, error-email, error-password, error-country, or error-accept-terms exist in the DOM; no form-success-alert exists; submit-form-button is enabled and shows text 'Create account'.
    - expect: None of the error-* testid elements are present
    - expect: form-success-alert is not present
    - expect: submit-form-button is enabled with text 'Create account'
  3. Fill input-full-name with 'Jane Tester'.
    - expect: Field reflects the typed value 'Jane Tester'
  4. Fill input-email with 'jane.tester@example.com'.
    - expect: Field reflects the typed value
  5. Fill input-password with a valid password of 12 characters, e.g. 'validPass123'.
    - expect: Field reflects the typed value (masked)
  6. Select 'India' (or any non-placeholder option) from select-country using selectOption, since this is a native HTML <select>.
    - expect: select-country value becomes the selected option, no longer 'Select a country…'
  7. Click checkbox-accept-terms to check it.
    - expect: checkbox-accept-terms becomes checked
  8. Leave all optional fields (Age, Bio, Plan radio group, Interests checkboxes, Experience range slider, Preferred start date, Resume upload) untouched at their defaults.
    - expect: Optional fields remain at default values (e.g. Plan defaults to 'Basic', Experience defaults to 3) and do not block submission
  9. Click submit-form-button.
    - expect: Immediately/briefly after the click, submit-form-button becomes disabled and its text changes to 'Submitting…'
    - expect: No error-* elements appear during this transient state
  10. Wait for the submission to resolve (poll/wait up to ~2 seconds).
    - expect: submit-form-button re-enables and its text reverts to 'Create account'
    - expect: form-success-alert becomes visible with the exact text: 'Submitted successfully! Registered Jane Tester (jane.tester@example.com).'
    - expect: No error-* testid elements are present after success

#### 1.2. Submitting with only mandatory fields filled (all optional fields left blank/default) still succeeds

**File:** `apps/practice-target/tests/forms/happy-path.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: Forms page loads with the sign-up form in its default blank state
  2. Fill input-full-name with 'Alex Optional', fill input-email with 'alex.optional@example.com', fill input-password with 'optionalPass1' (13 chars), select-country to 'United Kingdom', and check checkbox-accept-terms. Do not touch input-age, input-bio, radio-group-plan, checkbox-group-interests, input-experience-range, input-start-date, or input-resume-upload.
    - expect: All five mandatory fields hold the specified values; optional fields remain untouched
  3. Click submit-form-button and wait for the async submission to resolve.
    - expect: Button shows 'Submitting…' then reverts to 'Create account'
    - expect: form-success-alert shows text: 'Submitted successfully! Registered Alex Optional (alex.optional@example.com).'
    - expect: No error-* elements are present
    - expect: This confirms optional fields are not required for a successful submission (business rule 1)

#### 1.3. Password at exactly the 8-character minimum boundary is accepted

**File:** `apps/practice-target/tests/forms/happy-path.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: Forms page loads with the sign-up form in its default blank state
  2. Fill input-full-name with 'Boundary Tester', fill input-email with 'boundary.tester@example.com', fill input-password with exactly 8 characters: 'abcd1234', select-country to 'Japan', and check checkbox-accept-terms.
    - expect: All five mandatory fields hold the specified values, password field contains exactly 8 characters
  3. Click submit-form-button and wait for the submission to resolve.
    - expect: No error-password element appears (8 characters satisfies the 'Minimum 8 characters.' hint shown near the password field)
    - expect: form-success-alert shows text: 'Submitted successfully! Registered Boundary Tester (boundary.tester@example.com).'

### 2. Mandatory Field Validation

**Seed:** `apps/practice-target/seed.spec.ts`

#### 2.1. No validation errors are shown before the first submit attempt

**File:** `apps/practice-target/tests/forms/validation.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: No error-* testid elements exist in the DOM
  2. Click into input-full-name, type a few characters, then click elsewhere (e.g. click on input-email label area) to blur the field without submitting.
    - expect: No error-full-name or any other error-* element appears as a result of blurring (confirms there is no live/on-blur validation per business rule 2)
  3. Click into input-email and input-password, type and then clear the values (leaving them blank again), without clicking submit-form-button.
    - expect: Still no error-* testid elements are present anywhere on the page

#### 2.2. Submitting a completely empty form shows all five mandatory field errors and no success alert (AC2)

**File:** `apps/practice-target/tests/forms/validation.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load. Do not fill in any field.
    - expect: Form is in its default blank state
  2. Click submit-form-button.
    - expect: The submit action completes synchronously/quickly for the validation-failure path (no 'Submitting…' success flow is required to observe errors)
  3. Assert the following five error elements are visible with their exact text.
    - expect: error-full-name has text 'Full name is required.'
    - expect: error-email has text 'Email is required.'
    - expect: error-password has text 'Password is required.'
    - expect: error-country has text 'Please select a country.'
    - expect: error-accept-terms has text 'You must accept the terms to continue.'
  4. Assert that form-success-alert does not exist in the DOM.
    - expect: No success alert is rendered when validation fails
  5. Assert submit-form-button is enabled and shows 'Create account' (not stuck in a 'Submitting…' state) since the request never reached the async submit phase.
    - expect: Button is back to its normal clickable state

#### 2.3. Fixing only some invalid fields and resubmitting clears only the corresponding errors while leaving the rest

**File:** `apps/practice-target/tests/forms/validation.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: Form is in its default blank state
  2. Click submit-form-button on the empty form to generate all five errors.
    - expect: All five error-* elements described in the empty-submit test are visible
  3. Fill input-full-name with 'Partial Fixer' and fill input-email with 'partial.fixer@example.com'. Do NOT fill password, select a country, or check the terms checkbox. Do not click submit yet.
    - expect: The previously shown error-full-name and error-email text is still visible/unchanged on screen (errors do not auto-clear on input change, only on next submit, per observed behavior)
  4. Click submit-form-button again.
    - expect: error-full-name and error-email are no longer present (resolved by the filled values)
    - expect: error-password still shows 'Password is required.'
    - expect: error-country still shows 'Please select a country.'
    - expect: error-accept-terms still shows 'You must accept the terms to continue.'
    - expect: form-success-alert is still not present since the form remains invalid

### 3. Field-Level Boundary and Format Validation

**Seed:** `apps/practice-target/seed.spec.ts`

#### 3.1. Password below the 8-character minimum shows a dedicated length error on submit

**File:** `apps/practice-target/tests/forms/field-validation.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: Form is in its default blank state
  2. Fill input-full-name with 'Jane Tester', fill input-email with 'jane.tester@example.com', fill input-password with a 7-character value 'abc1234', select-country to 'India', and check checkbox-accept-terms.
    - expect: All fields hold the specified values, password field contains exactly 7 characters
  3. Click submit-form-button.
    - expect: error-password is visible with the exact text 'Password must be at least 8 characters.' (distinct from the empty-field message 'Password is required.')
    - expect: No other error-* elements are present since all other mandatory fields are valid
    - expect: form-success-alert is not present
  4. Without clicking submit again, update input-password to a valid 8+ character value, e.g. 'abc12345', and assert the DOM state immediately after typing (before clicking submit again).
    - expect: error-password with text 'Password must be at least 8 characters.' is still present/unchanged, confirming errors only re-evaluate on the next submit click, not live as you type
  5. Click submit-form-button again and wait for the async submission to resolve.
    - expect: error-password is no longer present
    - expect: form-success-alert shows text: 'Submitted successfully! Registered Jane Tester (jane.tester@example.com).'

#### 3.2. Invalid email format shows a format-specific error distinct from the required-field error

**File:** `apps/practice-target/tests/forms/field-validation.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: Form is in its default blank state
  2. Fill input-full-name with 'Jane Tester', fill input-email with an invalid format value 'not-an-email' (no @ or domain), fill input-password with a valid value 'validpass123', select-country to 'Germany', and check checkbox-accept-terms.
    - expect: All fields hold the specified values, email field contains an invalid-format string
  3. Click submit-form-button.
    - expect: error-email is visible with the exact text 'Enter a valid email address.' (distinct from 'Email is required.')
    - expect: No other error-* elements are present
    - expect: form-success-alert is not present
  4. Fix input-email to a valid value 'jane.tester@example.com' and click submit-form-button again, waiting for the submission to resolve.
    - expect: error-email is no longer present
    - expect: form-success-alert shows text: 'Submitted successfully! Registered Jane Tester (jane.tester@example.com).'

### 4. Submit Button Transient State

**Seed:** `apps/practice-target/seed.spec.ts`

#### 4.1. Submit button is disabled and shows 'Submitting…' while the async submission is in-flight on a valid form

**File:** `apps/practice-target/tests/forms/submit-state.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: Form is in its default blank state
  2. Fill all mandatory fields with valid values: input-full-name 'State Tester', input-email 'state.tester@example.com', input-password 'statePass123', select-country 'Brazil', and check checkbox-accept-terms.
    - expect: All five mandatory fields hold valid values
  3. Before clicking, assert submit-form-button is enabled and reads 'Create account'.
    - expect: Button is enabled with text 'Create account'
  4. Click submit-form-button, then immediately (within the same tick / a very short wait, e.g. ~50-100ms) read the button's disabled attribute and text.
    - expect: submit-form-button.isDisabled() is true
    - expect: submit-form-button text is 'Submitting…'
  5. Wait for form-success-alert to become visible (up to ~2 seconds).
    - expect: form-success-alert is visible with text 'Submitted successfully! Registered State Tester (state.tester@example.com).'
    - expect: submit-form-button is re-enabled and its text has reverted to 'Create account'

#### 4.2. Submit button does NOT enter the 'Submitting…' async state when the form fails client-side validation

**File:** `apps/practice-target/tests/forms/submit-state.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load. Leave the form empty.
    - expect: Form is in its default blank state
  2. Click submit-form-button and immediately check its text/disabled state.
    - expect: submit-form-button text never becomes 'Submitting…' (validation fails before the async submit phase begins)
    - expect: submit-form-button remains enabled and reads 'Create account'
    - expect: The five mandatory-field errors (error-full-name, error-email, error-password, error-country, error-accept-terms) are visible instead

### 5. UI Element Presence and Labeling

**Seed:** `apps/practice-target/seed.spec.ts`

#### 5.1. All sign-up form fields and controls render with correct labels/types on page load

**File:** `apps/practice-target/tests/forms/ui-elements.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: Forms page loads successfully
  2. Assert the 'Create account' heading is visible and the signup-form (data-testid) element is present.
    - expect: Heading level 2 'Create account' is visible; form element with testid signup-form exists
  3. Assert input-full-name is visible, is an empty text input, and is associated with a visible 'Full name' label text.
    - expect: Textbox is present, type=text, initial value is empty
  4. Assert input-email is visible, is an empty input of type email, associated with label text 'Email'.
    - expect: Input present, type=email, initial value empty
  5. Assert input-password is visible, is an empty input of type password, associated with label text 'Password', and that the helper text 'Minimum 8 characters.' is visible nearby.
    - expect: Input present, type=password, helper hint text visible
  6. Assert toggle-password-visibility button (labeled 'Show') is visible next to the password field. Click it once and verify the password input's type attribute toggles from 'password' to 'text', then click again to confirm it toggles back to 'password'.
    - expect: Clicking 'Show' reveals the password as plain text (type=text); clicking again (now likely labeled 'Hide') masks it again (type=password)
  7. Assert select-country is a native <select> element (tagName === 'SELECT'), its default selected option is the 'Select a country…' placeholder, and it contains options for United States, United Kingdom, India, Germany, Japan, and Brazil.
    - expect: select-country is confirmed as a native HTML select with the placeholder selected by default and the six country options present
  8. Assert checkbox-accept-terms is visible, is of type checkbox, unchecked by default, and labeled 'I accept the terms and conditions'.
    - expect: Checkbox present and unchecked initially
  9. Assert submit-form-button is visible, enabled, and reads 'Create account'; assert reset-form-button is visible and reads 'Reset'.
    - expect: Both buttons are present with correct default labels
  10. Assert the optional fields are present but not required: input-age (type=number), input-bio (textarea), radio-group-plan with radio-plan-basic checked by default, radio-plan-pro and radio-plan-enterprise unchecked, checkbox-group-interests with checkbox-interest-automation/design/performance/accessibility/security all unchecked by default, input-experience-range (type=range) defaulting to a value of 3, input-start-date (type=date), and input-resume-upload (type=file).
    - expect: All optional controls are present with the documented default values/states, confirming they are not part of the mandatory validation set per business rule 1

#### 5.2. Reset button clears user-entered values and any shown validation errors

**File:** `apps/practice-target/tests/forms/ui-elements.spec.ts`

**Steps:**
  1. Navigate to /forms with a fresh page load.
    - expect: Form is in its default blank state
  2. Fill input-full-name with 'Temp Value' and fill input-email with 'temp@example.com', then click submit-form-button on the otherwise-empty form to also generate validation errors for the remaining required fields.
    - expect: error-password, error-country, and error-accept-terms are visible (full name and email are filled so their errors do not appear)
  3. Click reset-form-button.
    - expect: input-full-name and input-email are cleared back to empty
    - expect: Any previously visible error-* elements are no longer present (this should be verified live; if errors persist after reset, note the actual observed behavior instead of assuming)
    - expect: select-country reverts to the 'Select a country…' placeholder and checkbox-accept-terms reverts to unchecked
