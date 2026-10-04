# End-to-End QA Workflow with Natural Language

## Workflow Overview

This prompt guides you through a complete 7-step QA workflow using MCP servers and AI agents to go from user story to automated test scripts delivered as a pull request.

The harness can test more than one application. Each run works on **one active story**. Every step below uses `{PLACEHOLDERS}` that you fill in from that story's row in the registry.

---

## 🧭 Run Configuration (resolve this before Step 1)

### Choosing the active story

1. The kick-off prompt names the active story (e.g. `Active story: SCRUM-201`).
2. If no story is named, ask the user which story to run. Don't guess.
3. Look the story up in the **Story registry**, then look its app up in **Target applications**. Together they define every placeholder.
4. State the resolved values at the start of Step 1 so the user can catch a wrong pick.

### Target applications

| App | `{BASE_URL}` | `{SEED}` | `{CHROMIUM_PROJECT}` | All browser projects | Locator convention | `{TARGET_REPO}` (default branch `master`) |
|---|---|---|---|---|---|---|
| `saucedemo` | `https://www.saucedemo.com` | `tests/saucedemo/seed.spec.ts` (logs in as `standard_user`, lands on `/inventory.html`) | `chromium` | `chromium`, `firefox`, `webkit`, `Mobile Chrome` | `data-test` attributes: `page.locator('[data-test="…"]')` | [`prashant-kiit/e2e-playwright-agent-test-target`](https://github.com/prashant-kiit/e2e-playwright-agent-test-target) |
| `practice` | `https://custom-test-target-app.vercel.app` | `tests/practice-target/seed.spec.ts` (home page `/`, **not** logged in) | `practice-chromium` | `practice-chromium`, `practice-firefox`, `practice-webkit`, `practice-mobile-chrome` | `data-testid` attributes: `page.getByTestId('…')` | [`prashant-kiit/e2e-playwright-test-custom-target`](https://github.com/prashant-kiit/e2e-playwright-test-custom-target) |

Each app is delivered to its own target repo. Never push one app's artifacts to another app's repo.

Both apps share one `playwright.config.ts`. Each app has its own folder under `tests/` (seed included), and its projects only pick up that folder (`tests/saucedemo/**` runs only in the SauceDemo projects, `tests/practice-target/**` only in the `practice-*` projects). Each set of projects has its own `baseURL`. Consequences:
- `npx playwright test {TEST_DIR}` already runs exactly the right 4 browser projects, so no `--project` filter is needed for the cross-browser run.
- Always pass `project: "{CHROMIUM_PROJECT}"` and `seedFile: "{SEED}"` to `planner_setup_page` and `generator_setup_page`. Left out, they use the first project (`chromium`, which is SauceDemo) and create a default seed file instead of using the app's seed.

### Story registry

| `{STORY_ID}` | App | `{STORY_FILE}` | `{PLAN_FILE}` | `{TEST_DIR}` | `{REPORT_FILE}` | `{BRANCH}` |
|---|---|---|---|---|---|---|
| SCRUM-101 | `saucedemo` | `user-stories/saucedemo/SCRUM-101-checkout.md` | `specs/saucedemo/SCRUM-101-checkout-test-plan.md` | `tests/saucedemo/checkout/` | `reports/SCRUM-101-checkout-test-report.md` | `qa/SCRUM-101-checkout` *(already delivered in PR #1 at the old paths `user-stories/scrum-latest.md`, `specs/saucedemo-checkout-test-plan.md`, `tests/seed.spec.ts` and `tests/saucedemo-checkout/`; a re-run must use a new name, e.g. `qa/SCRUM-101-checkout-v2`, and should delete those old paths in the same commit)* |
| SCRUM-102 | `saucedemo` | `user-stories/saucedemo/SCRUM-102-login.md` | `specs/saucedemo/SCRUM-102-login-test-plan.md` | `tests/saucedemo/login/` | `reports/SCRUM-102-login-test-report.md` | `qa/SCRUM-102-login` |
| SCRUM-103 | `saucedemo` | `user-stories/saucedemo/SCRUM-103-product-catalog.md` | `specs/saucedemo/SCRUM-103-product-catalog-test-plan.md` | `tests/saucedemo/product-catalog/` | `reports/SCRUM-103-product-catalog-test-report.md` | `qa/SCRUM-103-product-catalog` |
| SCRUM-104 | `saucedemo` | `user-stories/saucedemo/SCRUM-104-product-details.md` | `specs/saucedemo/SCRUM-104-product-details-test-plan.md` | `tests/saucedemo/product-details/` | `reports/SCRUM-104-product-details-test-report.md` | `qa/SCRUM-104-product-details` |
| SCRUM-105 | `saucedemo` | `user-stories/saucedemo/SCRUM-105-shopping-cart.md` | `specs/saucedemo/SCRUM-105-shopping-cart-test-plan.md` | `tests/saucedemo/shopping-cart/` | `reports/SCRUM-105-shopping-cart-test-report.md` | `qa/SCRUM-105-shopping-cart` |
| SCRUM-106 | `saucedemo` | `user-stories/saucedemo/SCRUM-106-menu-navigation.md` | `specs/saucedemo/SCRUM-106-menu-navigation-test-plan.md` | `tests/saucedemo/menu-navigation/` | `reports/SCRUM-106-menu-navigation-test-report.md` | `qa/SCRUM-106-menu-navigation` |
| SCRUM-107 | `saucedemo` | `user-stories/saucedemo/SCRUM-107-dynamic-catalog.md` | `specs/saucedemo/SCRUM-107-dynamic-catalog-test-plan.md` | `tests/saucedemo/dynamic-catalog/` | `reports/SCRUM-107-dynamic-catalog-test-report.md` | `qa/SCRUM-107-dynamic-catalog` |
| SCRUM-201 | `practice` | `user-stories/practice-target/SCRUM-201-auth.md` | `specs/practice-target/SCRUM-201-auth-test-plan.md` | `tests/practice-target/auth/` | `reports/SCRUM-201-auth-test-report.md` | `qa/SCRUM-201-auth` |
| SCRUM-202 | `practice` | `user-stories/practice-target/SCRUM-202-forms.md` | `specs/practice-target/SCRUM-202-forms-test-plan.md` | `tests/practice-target/forms/` | `reports/SCRUM-202-forms-test-report.md` | `qa/SCRUM-202-forms` |
| SCRUM-203 | `practice` | `user-stories/practice-target/SCRUM-203-buttons.md` | `specs/practice-target/SCRUM-203-buttons-test-plan.md` | `tests/practice-target/buttons/` | `reports/SCRUM-203-buttons-test-report.md` | `qa/SCRUM-203-buttons` |
| SCRUM-204 | `practice` | `user-stories/practice-target/SCRUM-204-modals.md` | `specs/practice-target/SCRUM-204-modals-test-plan.md` | `tests/practice-target/modals/` | `reports/SCRUM-204-modals-test-report.md` | `qa/SCRUM-204-modals` |
| SCRUM-205 | `practice` | `user-stories/practice-target/SCRUM-205-dropdowns.md` | `specs/practice-target/SCRUM-205-dropdowns-test-plan.md` | `tests/practice-target/dropdowns/` | `reports/SCRUM-205-dropdowns-test-report.md` | `qa/SCRUM-205-dropdowns` |
| SCRUM-206 | `practice` | `user-stories/practice-target/SCRUM-206-table.md` | `specs/practice-target/SCRUM-206-table-test-plan.md` | `tests/practice-target/table/` | `reports/SCRUM-206-table-test-report.md` | `qa/SCRUM-206-table` |
| SCRUM-207 | `practice` | `user-stories/practice-target/SCRUM-207-dynamic-content.md` | `specs/practice-target/SCRUM-207-dynamic-content-test-plan.md` | `tests/practice-target/dynamic-content/` | `reports/SCRUM-207-dynamic-content-test-report.md` | `qa/SCRUM-207-dynamic-content` |
| SCRUM-208 | `practice` | `user-stories/practice-target/SCRUM-208-navigation.md` | `specs/practice-target/SCRUM-208-navigation-test-plan.md` | `tests/practice-target/navigation/` | `reports/SCRUM-208-navigation-test-report.md` | `qa/SCRUM-208-navigation` |

Derived values:
- `{STORY_TITLE}`: the title after the ID in the story's first heading (e.g. "Account Sign-up Form").
- `{PR_TITLE}`: `{STORY_ID}: {STORY_TITLE} E2E test suite`.
- Screenshots: `reports/evidence/{STORY_ID}-*.png`.

To add a story: put the story file under `user-stories/` and add a row here. To add an app: add a row to Target applications (including its target repo), a folder `tests/<app>/` with its seed, and a set of browser projects with their own `baseURL` and `testMatch: '**/<app>/**/*.spec.ts'` in `playwright.config.ts`. Nothing for the existing apps needs to change.

### Fixed conventions

| Item | Value |
|---|---|
| URLs in tests | Relative paths in `page.goto` (each project sets `baseURL`) |
| Browsers | Already configured in `playwright.config.ts`. Don't change the config, and keep `chromium` as the first project |

Do not write anything into `test-results/`: Playwright wipes it on every run and it is git-ignored.

---

## 🎯 STEP 1: Read User Story

**Prompt:**

```
I need to start a new testing workflow for {STORY_ID}. First state the resolved run
configuration (story file, app, base URL, seed, Chromium project, plan, test directory,
report, branch, target repo). Then read the user story from:
{STORY_FILE}

Summarize the key requirements, acceptance criteria, and testing scope.
```

**Expected Output:**

- Resolved run configuration
- Summary of the user story
- List of acceptance criteria
- Application URL and test credentials (if any)
- Key features to test

---



## 📄 STEP 2: Create Test Plan

**Prompt:**

```
Based on the user story {STORY_ID} that we just reviewed, use the playwright-test-planner
agent to:

1. Read the application URL and test credentials (if any) from the user story
2. Explore the application and understand all workflows mentioned in the acceptance
   criteria. Set up the browser with planner_setup_page using
   seedFile "{SEED}" and project "{CHROMIUM_PROJECT}" (the seed already opens the app
   at {BASE_URL})
3. Create a comprehensive test plan that covers all acceptance criteria including:
   - Happy path scenarios
   - Negative scenarios (validation errors, empty fields, invalid data)
   - Edge cases and boundary conditions
   - Navigation flow tests
   - UI element validation

4. Save the test plan as: {PLAN_FILE}

Ensure each test scenario includes:
- Clear test case title
- Detailed step-by-step instructions
- Expected results for each step
- Test data requirements
- The stable locators found (following the app's locator convention)
```

**Expected Output:**

- Complete test plan markdown file saved to {PLAN_FILE}
- Organized test scenarios with clear structure
- Browser exploration screenshots (if needed)

---



## 🧪 STEP 3: Perform Exploratory Testing

**Prompt:**

```
Now I need to perform manual exploratory testing using Playwright MCP browser tools.

Please read the test plan from: {PLAN_FILE}

Then execute the test scenarios defined in that plan:
1. Start a browser session from the seed test using the playwright-test MCP setup tool
   (seedFile "{SEED}", project "{CHROMIUM_PROJECT}"), then use the Playwright browser
   tools to manually execute each test scenario from the plan
2. Follow the step-by-step instructions in each test case
3. Verify expected results match actual results
4. Take screenshots at key steps and error states, saved as
   reports/evidence/{STORY_ID}-<short-name>.png
5. Document your findings:
   - Test execution results for each scenario
   - Any UI inconsistencies or unexpected behaviors
   - Missing validations or bugs discovered
   - Screenshots as evidence
   - The locators that worked for each element (needed in Step 4)
```

**Expected Output:**

- Manual test execution results
- Screenshots of the application at various states
- List of observations and findings
- Any issues discovered during exploration

---



## ⚙️ STEP 4: Generate Automation Scripts

**Prompt:**

```
Now I need to create automated test scripts using the playwright-test-generator agent.

Please review:
1. Test plan from: {PLAN_FILE} (for test scenarios and steps)
2. Exploratory testing results from Step 3 (for actual element selectors and UI insights)

Using insights from the manual exploratory testing:
- Leverage the element selectors and locators that were successfully used in Step 3
- Use stable element properties (the app's test-id attribute, roles, IDs) discovered
  during exploration
- Apply wait strategies and UI behaviors observed during manual testing
- Incorporate any workarounds for UI quirks discovered

Generate Playwright TypeScript automation scripts:
1. Create scripts for each test scenario from the test plan
2. Organize scripts into appropriate test suite files in: {TEST_DIR}
   (one *.spec.ts file per acceptance criterion or feature area)
3. Use the test case names and steps from the test plan
4. Use reliable selectors and strategies from exploratory testing
5. Call generator_setup_page with seedFile "{SEED}" and project "{CHROMIUM_PROJECT}"

Requirements for all scripts:
- Follow Playwright best practices
- Include proper assertions using expect()
- Use descriptive test names matching the format in the test plan
- Use robust element selectors discovered during manual testing
- Add comments for complex steps
- Use proper wait strategies based on actual application behavior (no fixed timeouts)
- Add proper test hooks (beforeEach, afterEach). Repeat the seed's setup steps in
  beforeEach; don't import the seed file
- Use relative URLs (baseURL is set per project in playwright.config.ts)
- Do not change playwright.config.ts: the browser projects for every app are already
  configured there

After generating the scripts, run them on Chromium only to verify they pass:
npx playwright test {TEST_DIR} --project={CHROMIUM_PROJECT}
```

**Expected Output:**

- Test suite files created in {TEST_DIR} based on test plan scenarios
- Scripts using robust selectors discovered during exploratory testing
- All scripts follow Playwright best practices
- Initial test generation complete

---



## 🔧 STEP 5: Execute and Heal Automation Tests

**Prompt:**

```
Now I need to execute the generated automation scripts and heal any failures using the
playwright-test-healer agent.

1. Run all automation scripts on Chromium:
   npx playwright test {TEST_DIR} --project={CHROMIUM_PROJECT}
2. Identify any failing tests
3. For each failing test, use the playwright-test-healer agent to:
   - Analyze the failure (selector issues, timing issues, assertion failures)
   - Auto-heal the test by fixing selectors, adding waits, or adjusting assertions
   - Update the test script with the fixes
   (Tell the healer the test directory and the project name: test_run takes
   locations ["{TEST_DIR}"] and projects ["{CHROMIUM_PROJECT}"].)
4. Re-run the healed tests on Chromium to verify they pass
5. Repeat the heal process until all tests are stable and passing on Chromium
6. Final cross-browser run once Chromium is green:
   npx playwright test {TEST_DIR}
   (this runs the app's 4 browser projects listed in Target applications). Heal any
   browser-specific failures, then re-run that browser with --project=<name>.
   If an interaction has no equivalent on a browser (e.g. right-click on the mobile
   project), skip it there with test.skip and a reason, and record it in the report.
7. Document:
   - Initial test results (pass/fail count)
   - Healing activities performed
   - Final test results after healing, per browser
   - Any tests that couldn't be auto-healed
```

**Expected Output:**

- All automation tests executed
- Failing tests identified and healed using test-healer agent
- Healed test scripts updated in {TEST_DIR}
- Final stable test execution results across all four browser projects
- Summary of healing activities performed

---



## 📊 STEP 6: Create Test Report

**Prompt:**

```
Now I need to create a comprehensive test execution report based on manual testing,
automation execution, and healing activities.

Please compile results from:
- Step 3: Manual exploratory testing results
- Step 4: Generated automation scripts
- Step 5: Automated test execution and healing results

Save the report as: {REPORT_FILE}
(not under test-results/, which Playwright deletes on every run)

Include:
1. Executive Summary
   - Story, application and base URL tested
   - Total test cases planned
   - Test cases executed (manual + automated)
   - Overall Pass/Fail/Blocked status

2. Manual Test Results
   - Results from Step 3 exploratory testing
   - Screenshots and observations
   - Issues found during manual testing

3. Automated Test Results
   - Initial automation results from Step 5
   - Healing activities performed
   - Final test execution results after healing
   - Test suite execution summary
   - Pass/Fail/Skipped count for each test suite and each browser project

4. Defects Log
   - For any failed tests (manual or automated):
     * Bug ID
     * Severity (Critical/High/Medium/Low)
     * Title and Description
     * Steps to Reproduce
     * Expected vs Actual Behavior
     * Screenshots/Evidence
     * Environment Details

5. Test Coverage Analysis
   - Which acceptance criteria are covered
   - Coverage from manual vs automated tests
   - Any gaps in test coverage
   - Recommendations for additional testing

6. Summary and Recommendations
   - Overall quality assessment
   - Risk areas
   - Next steps
```

**Expected Output:**

- Comprehensive test execution report covering both manual and automated testing
- Clear PASS/FAIL status for all test scenarios
- Detailed bug reports for failures
- Complete test coverage analysis
- Evidence and screenshots attached

---



## 🚀 STEP 7: Open a Pull Request in the Target Repository

**Target repository:** `{TARGET_REPO}` from the Target applications table (default branch `master`)

**Prompt:**

```
Now I need to deliver the test artifacts to the target repository using the GitHub MCP
server ({TARGET_REPO}). Do not use local
git commands and do not commit to this workspace repository.

1. Check whether the target repository has any commits.
   If it is empty, first push one bootstrap commit directly to master containing these
   workspace files at the same paths:
   - package.json
   - package-lock.json
   - playwright.config.ts
   - .gitignore
   - .github/workflows/playwright.yml
   - {SEED}
   Commit message: "chore: bootstrap Playwright project"

2. Check that {BRANCH} doesn't already exist in the target repo. If it does, stop and
   ask the user for a new branch name. Then create {BRANCH} from master.

3. Push these files to that branch, at the same paths as in the workspace:
   - {STORY_FILE}
   - {PLAN_FILE}
   - {TEST_DIR}*.spec.ts
   - {REPORT_FILE}
   - reports/evidence/{STORY_ID}-*.png (if any)
   Shared files: also push playwright.config.ts and {SEED} if they are missing on
   master or differ from the workspace copies (skip whatever the bootstrap just pushed). The target repo's CI runs
   `npx playwright test`, so it needs the app's browser projects and seed.
   Commit message:
   "feat(tests): Add complete test suite for {STORY_ID} {STORY_TITLE}

   - Add user story documentation
   - Add comprehensive test plan with all scenarios
   - Add test execution report with results
   - Add automated test scripts
   - Include validation, navigation, and edge case tests

   Resolves {STORY_ID}"

4. Open a pull request from {BRANCH} into master titled "{PR_TITLE}", with a body
   summarising the application tested, test counts, per-browser results, skipped tests
   and any open defects from the report.

5. Provide a summary of what was pushed and the pull request URL
```

**Expected Output:**

- Bootstrap commit on master of {TARGET_REPO} (first run against that repo only)
- Branch {BRANCH} with all test artifacts (plus shared config/seed if they changed)
- Pull request opened into master
- Pull request URL and summary of changes

---



## 🔁 Complete Workflow (Single Prompt)

**Prompt:**

```
I want to demonstrate a complete end-to-end QA workflow using natural language and MCP
servers for the active story {STORY_ID}. Resolve every {PLACEHOLDER} from the Run
Configuration section of qa_system_prompt.md first.

STEP 1 - READ USER STORY:
State the resolved run configuration, then read the user story from: {STORY_FILE}
Provide a brief summary of what needs to be tested.

STEP 2 - CREATE TEST PLAN:
Use the playwright-test-planner agent to create a comprehensive test plan based on the user
story. The agent should set up the page with seedFile {SEED} and project
{CHROMIUM_PROJECT}, explore the application and cover all acceptance criteria. Save it as:
{PLAN_FILE}

STEP 3 - EXPLORATORY TESTING:
Read the test plan from {PLAN_FILE} and use Playwright browser tools (same seed and
project) to manually execute each test scenario. Document findings with screenshots, note
any issues discovered, and record the locators that worked.

STEP 4 - GENERATE AUTOMATION SCRIPTS:
Review both the test plan ({PLAN_FILE}) and exploratory testing results from Step 3. Use
the playwright-test-generator agent (same seed and project) to create TypeScript
automation scripts leveraging the element selectors and insights discovered during manual
testing. Save scripts in {TEST_DIR}.

STEP 5 - EXECUTE AND HEAL TESTS:
Run all automation scripts from {TEST_DIR} with --project={CHROMIUM_PROJECT}. Use the
playwright-test-healer agent to identify and auto-heal any failing tests. Re-run until all
are stable and passing on Chromium, then do one final run across the app's browser
projects (npx playwright test {TEST_DIR}) and heal any browser-specific failures.
Document healing activities.

STEP 6 - CREATE TEST REPORT:
Create a comprehensive test execution report at: {REPORT_FILE}
Compile results from Step 3 (manual testing), Step 4 (script generation), and Step 5
(execution and healing). Include PASS/FAIL status per browser, healing summary, defects
log, and test coverage analysis.

STEP 7 - OPEN A PULL REQUEST:
Using the GitHub MCP server, deliver the artifacts to {TARGET_REPO} (the active app's repo)
as described in Step 7 of qa_system_prompt.md: bootstrap master if the repo is empty,
push the user story, test plan, tests, report (and shared config/seed if changed) to
branch {BRANCH}, and open a pull request into master titled "{PR_TITLE}".

Execute this complete workflow and provide status updates after each step.
```
