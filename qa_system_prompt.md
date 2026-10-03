# End-to-End QA Workflow with Natural Language

## Workflow Overview

This prompt guides you through a complete 7-step QA workflow using MCP servers and AI agents to go from user story to automated test scripts delivered as a pull request.

**Conventions used by every step:**

| Item | Value |
|---|---|
| User story | `user-stories/scrum-latest.md` |
| Test plan | `specs/saucedemo-checkout-test-plan.md` |
| Test scripts (TypeScript) | `tests/saucedemo-checkout/*.spec.ts` |
| Test report | `reports/SCRUM-101-checkout-test-report.md` |
| Target repo | `prashant-kiit/e2e-playwright-agent-test-target` (default branch `master`) |
| Seed test | `tests/seed.spec.ts` (already logs in as `standard_user` and lands on `/inventory.html`) |
| Base URL | `https://www.saucedemo.com` (set in `playwright.config.ts`, so use relative paths in `page.goto`) |

Do not write anything into `test-results/`: Playwright wipes it on every run and it is git-ignored.

---

## 🎯 STEP 1: Read User Story

**Prompt:**

```
I need to start a new testing workflow. Please read the user story from the file:
user-stories/scrum-latest.md

Summarize the key requirements, acceptance criteria, and testing scope.
```

**Expected Output:**

- Summary of the user story
- List of acceptance criteria
- Application URL and test credentials
- Key features to test

---



## 📄 STEP 2: Create Test Plan

**Prompt:**

```
Based on the user story SCRUM-101 that we just reviewed, use the playwright-test-planner
agent to:

1. Read the application URL and test credentials from the user story
2. Explore the application and understand all workflows mentioned in the acceptance
criteria (the seed test tests/seed.spec.ts already logs in)
3. Create a comprehensive test plan that covers all acceptance criteria including:
   - Happy path scenarios
   - Negative scenarios (validation errors, empty fields, invalid data)
   - Edge cases and boundary conditions
   - Navigation flow tests
   - UI element validation

4. Save the test plan as: specs/saucedemo-checkout-test-plan.md

Ensure each test scenario includes:
- Clear test case title
- Detailed step-by-step instructions
- Expected results for each step
- Test data requirements
```

**Expected Output:**

- Complete test plan markdown file saved to specs/
- Organized test scenarios with clear structure
- Browser exploration screenshots (if needed)

---



## 🧪 STEP 3: Perform Exploratory Testing

**Prompt:**

```
Now I need to perform manual exploratory testing using Playwright MCP browser tools.

Please read the test plan from: specs/saucedemo-checkout-test-plan.md

Then execute the test scenarios defined in that plan:
1. Start a browser session from the seed test (tests/seed.spec.ts) using the
   playwright-test MCP setup tool, then use the Playwright browser tools to manually
   execute each test scenario from the plan
2. Follow the step-by-step instructions in each test case
3. Verify expected results match actual results
4. Take screenshots at key steps and error states
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
1. Test plan from: specs/saucedemo-checkout-test-plan.md (for test scenarios and steps)
2. Exploratory testing results from Step 3 (for actual element selectors and UI insights)

Using insights from the manual exploratory testing:
- Leverage the element selectors and locators that were successfully used in Step 3
- Use stable element properties (data-test attributes, roles, IDs) discovered during exploration
- Apply wait strategies and UI behaviors observed during manual testing
- Incorporate any workarounds for UI quirks discovered

Generate Playwright TypeScript automation scripts:
1. Create scripts for each test scenario from the test plan
2. Organize scripts into appropriate test suite files in: tests/saucedemo-checkout/
   (one *.spec.ts file per acceptance criterion or feature area)
3. Use the test case names and steps from the test plan
4. Use reliable selectors and strategies from exploratory testing

Requirements for all scripts:
- Follow Playwright best practices
- Include proper assertions using expect()
- Use descriptive test names matching the format in the test plan
- Use robust element selectors discovered during manual testing
- Add comments for complex steps
- Use proper wait strategies based on actual application behavior (no fixed timeouts)
- Add proper test hooks (beforeEach, afterEach)
- Use relative URLs (baseURL is set in playwright.config.ts)
- Do not change playwright.config.ts: browsers (Chromium, Firefox, WebKit, Mobile Chrome)
  are already configured there

After generating the scripts, run them on Chromium only to verify they pass:
npx playwright test tests/saucedemo-checkout/ --project=chromium
```

**Expected Output:**

- Test suite files created in tests/saucedemo-checkout/ based on test plan scenarios
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
   npx playwright test tests/saucedemo-checkout/ --project=chromium
2. Identify any failing tests
3. For each failing test, use the playwright-test-healer agent to:
   - Analyze the failure (selector issues, timing issues, assertion failures)
   - Auto-heal the test by fixing selectors, adding waits, or adjusting assertions
   - Update the test script with the fixes
4. Re-run the healed tests on Chromium to verify they pass
5. Repeat the heal process until all tests are stable and passing on Chromium
6. Final cross-browser run once Chromium is green:
   npx playwright test tests/saucedemo-checkout/
   (Chromium, Firefox, WebKit and Mobile Chrome). Heal any browser-specific failures,
   then re-run that browser with --project=<name>.
7. Document:
   - Initial test results (pass/fail count)
   - Healing activities performed
   - Final test results after healing, per browser
   - Any tests that couldn't be auto-healed
```

**Expected Output:**

- All automation tests executed
- Failing tests identified and healed using test-healer agent
- Healed test scripts updated in tests/saucedemo-checkout/
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

Save the report as: reports/SCRUM-101-checkout-test-report.md
(not under test-results/, which Playwright deletes on every run)

Include:
1. Executive Summary
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
   - Pass/Fail count for each test suite and each browser project

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

**Target repository:** [prashant-kiit/e2e-playwright-agent-test-target](https://github.com/prashant-kiit/e2e-playwright-agent-test-target) (default branch `master`)

**Prompt:**

```
Now I need to deliver the test artifacts to the target repository using the GitHub MCP
server (owner: prashant-kiit, repo: e2e-playwright-agent-test-target). Do not use local
git commands and do not commit to this workspace repository.

1. Check whether the target repository has any commits.
   If it is empty, first push one bootstrap commit directly to master containing these
   workspace files at the same paths:
   - package.json
   - package-lock.json
   - playwright.config.ts
   - .gitignore
   - .github/workflows/playwright.yml
   - tests/seed.spec.ts
   Commit message: "chore: bootstrap Playwright project"

2. Create a branch from master named: qa/SCRUM-101-checkout

3. Push these files to that branch, at the same paths as in the workspace:
   - user-stories/scrum-latest.md
   - specs/saucedemo-checkout-test-plan.md
   - tests/saucedemo-checkout/*.spec.ts
   - reports/SCRUM-101-checkout-test-report.md
   Commit message:
   "feat(tests): Add complete test suite for SCRUM-101 checkout workflow

   - Add user story documentation
   - Add comprehensive test plan with all scenarios
   - Add test execution report with results
   - Add automated test scripts for checkout process
   - Include validation, navigation, and edge case tests

   Resolves SCRUM-101"

4. Open a pull request from qa/SCRUM-101-checkout into master titled
   "SCRUM-101: Checkout E2E test suite", with a body summarising the test counts,
   per-browser results and any open defects from the report.

5. Provide a summary of what was pushed and the pull request URL
```

**Expected Output:**

- Bootstrap commit on master (first run only)
- Branch qa/SCRUM-101-checkout with all test artifacts
- Pull request opened into master
- Pull request URL and summary of changes

---



## 🔁 Complete Workflow (Single Prompt)

**Prompt:**

```
I want to demonstrate a complete end-to-end QA workflow using natural language and MCP
servers.

STEP 1 - READ USER STORY:
First, read the user story from: user-stories/scrum-latest.md
Provide a brief summary of what needs to be tested.

STEP 2 - CREATE TEST PLAN:
Use the playwright-test-planner agent to create a comprehensive test plan based on the user
story. The agent should explore the application URL from the user story and cover all
acceptance criteria. Save it as: specs/saucedemo-checkout-test-plan.md

STEP 3 - EXPLORATORY TESTING:
Read the test plan from specs/saucedemo-checkout-test-plan.md and use Playwright browser
tools to manually execute each test scenario. Document findings with screenshots, note
any issues discovered, and record the locators that worked.

STEP 4 - GENERATE AUTOMATION SCRIPTS:
Review both the test plan (specs/saucedemo-checkout-test-plan.md) and exploratory testing
results from Step 3. Use the playwright-test-generator agent to create TypeScript
automation scripts leveraging the element selectors and insights discovered during manual
testing. Save scripts in tests/saucedemo-checkout/.

STEP 5 - EXECUTE AND HEAL TESTS:
Run all automation scripts from tests/saucedemo-checkout/ with --project=chromium. Use the
playwright-test-healer agent to identify and auto-heal any failing tests. Re-run until all
are stable and passing on Chromium, then do one final run across all browser projects and
heal any browser-specific failures. Document healing activities.

STEP 6 - CREATE TEST REPORT:
Create a comprehensive test execution report at: reports/SCRUM-101-checkout-test-report.md
Compile results from Step 3 (manual testing), Step 4 (script generation), and Step 5
(execution and healing). Include PASS/FAIL status per browser, healing summary, defects
log, and test coverage analysis.

STEP 7 - OPEN A PULL REQUEST:
Using the GitHub MCP server, deliver the artifacts to prashant-kiit/e2e-playwright-agent-test-target
as described in Step 7 of qa_system_prompt.md: bootstrap master if the repo is empty,
push the user story, test plan, tests and report to branch qa/SCRUM-101-checkout, and open
a pull request into master.

Execute this complete workflow and provide status updates after each step.
```
