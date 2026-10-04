# End-to-End QA Workflow with Natural Language

## Workflow Overview

This prompt guides you through a 5-step QA workflow using MCP servers and AI agents to go from a user story to a healed, automated test suite on disk. **The agent stops after Step 5 for human review.** It does NOT deliver: a human reviews the generated test code and then runs `./push-artifacts.sh {APP} {STORY_ID}` to open the pull request in the target repo.

**The only way the flow is run is `run-stories.sh`** — one headless, unattended Claude Code session per story (see "Run contract" below). There is no interactive mode: every session runs with no human to answer questions, so you never ask; you apply a safe default and record it. The kick-off prompt always names the active story and a run-id.

The harness can test more than one application. Each run works on **one active story**. Every step below uses `{PLACEHOLDERS}` that you derive from the story file's location and the app's `app.json` (see Run Configuration).

---

## 🧭 Run Configuration (resolve this before Step 1)

Everything about an application under test lives in one folder, `apps/<app>/`. Nothing about a specific app is written in this prompt or in `playwright.config.ts`.

```
apps/<app>/
├── app.json                         # the app's only config (see below)
├── seed.spec.ts                     # brings the app to the starting state for every agent session
├── user-stories/<STORY_ID>-<slug>.md
├── specs/                           # generated: test plans
├── tests/<slug>/                    # generated: test suites
└── reports/                         # generated: reports, evidence/<STORY_ID>-*.png
```

`app.json` fields: `name`, `baseURL`, `targetRepo` (owner/repo that receives the tests), `targetBranch`, `locators` (how to locate elements in this app) and `agentNotes` (quirks every step must respect). `playwright.config.ts` discovers every `apps/<app>/app.json` (folders starting with `_` are skipped) and creates the projects `<app>-chromium`, `<app>-firefox`, `<app>-webkit` and `<app>-mobile-chrome`, each running only `apps/<app>/**` with that app's `baseURL`.

### Choosing the active story

1. The kick-off prompt always names the active story (e.g. `Active story: SCRUM-201`), injected by `run-stories.sh`.
2. If no story is named, end the run with a one-line error. Do not guess and do not ask — nobody can answer.
3. Find the one file matching `apps/*/user-stories/{STORY_ID}-*.md`. The folder it sits in is the app. If there is no match, or more than one, end the run with a one-line error.
4. Read `apps/{APP}/app.json`.
5. State the resolved values at the start of Step 1 (they are recorded in the session log).

### Placeholders

| Placeholder | Value |
|---|---|
| `{STORY_ID}` | From the kick-off prompt, e.g. `SCRUM-202` |
| `{APP}` | The folder name under `apps/` that holds the story, e.g. `practice-target` |
| `{SLUG}` | The story file name after `{STORY_ID}-`, without `.md`, e.g. `forms` |
| `{APP_DIR}` | `apps/{APP}` |
| `{STORY_FILE}` | `{APP_DIR}/user-stories/{STORY_ID}-{SLUG}.md` |
| `{STORY_TITLE}` | The title after the ID in the story's first heading, e.g. "Account Sign-up Form" |
| `{SEED}` | `{APP_DIR}/seed.spec.ts` |
| `{PLAN_FILE}` | `{APP_DIR}/specs/{STORY_ID}-{SLUG}-test-plan.md` |
| `{TEST_DIR}` | `{APP_DIR}/tests/{SLUG}/` |
| `{CHROMIUM_PROJECT}` | `{APP}-chromium` |
| `{BASE_URL}`, `{TARGET_REPO}`, `{TARGET_BRANCH}` | `baseURL`, `targetRepo`, `targetBranch` from `app.json` |
| `{BRANCH}` | `qa/{STORY_ID}-{SLUG}` |
| `{PR_TITLE}` | `{STORY_ID}: {STORY_TITLE} E2E test suite` |
| `{RUN_ID}` | The `Run-ID:` line in the kick-off prompt (e.g. `20261004-180531-saucedemo`), set by `run-stories.sh` for every run |

The placeholders `{TARGET_REPO}`, `{TARGET_BRANCH}`, `{BRANCH}` and `{PR_TITLE}` describe where a human later delivers the suite with `./push-artifacts.sh`; the agent itself never pushes or opens a PR.

Rules that follow from this layout:
- The agent generates and heals on `{CHROMIUM_PROJECT}` only (token saving). `npx playwright test {TEST_DIR}` (no `--project`) runs all 4 of the app's projects; that full run is for CI, not the agent.
- Always pass `project: "{CHROMIUM_PROJECT}"` and `seedFile: "{SEED}"` to `planner_setup_page` and `generator_setup_page`. Left out, they use the first project (whichever app sorts first) and create a default seed file.
- Locate elements the way `app.json` `locators` says, and follow every `agentNotes` entry in every step.

To add a story: drop `<STORY_ID>-<slug>.md` into `apps/<app>/user-stories/`. To add an app: copy `apps/_template/` to `apps/<new-app>/`, fill in `app.json`, write `seed.spec.ts` and the stories. Nothing else changes.

### Run contract (every run)

Every run is launched by `run-stories.sh`: one headless, unattended session per story, several at once, with `Mode: unattended` and a `Run-ID:` line in the kick-off prompt. All stories in a batch belong to the same app. These rules always apply:

1. **Never ask anyone.** There is no human in the session; asking just ends it. Wherever a step says "stop" on ambiguity, instead: for a missing/duplicate story file, end the run with a one-line error and do nothing else; for anything else unclear, make the most conservative choice that lets the run finish and record it in your final summary under "Unattended decisions".
2. **The run-id makes a rerun safe and traceable.** The script wipes this story's old generated files before restarting it, so you always start clean (never merge leftovers from an earlier attempt).
3. **The agent does not deliver.** You stop after Step 5 with the healed suite in `{TEST_DIR}`. A human reviews it and runs `./push-artifacts.sh` afterwards. Do not run `./push-artifacts.sh` and do not open a PR yourself.
4. **Other stories are running in this repo at the same time.** Write only your own story's files (`{PLAN_FILE}`, `{TEST_DIR}`). Never edit `playwright.config.ts`, any `app.json`, any seed or another story's files, and never delete other folders (e.g. `test-results/`, `runs/`).
5. Playwright output goes to the per-story folder in `QA_RUN_DIR` automatically. Run the commands exactly as written in the steps.
6. End with a short summary as your final message: story, app, the test files created in `{TEST_DIR}`, the Chromium pass/fail count after healing, open defects, and any "Unattended decisions". The batch script marks the story **ready-for-review** when the suite exists on disk and the session ended cleanly.

### Fixed conventions

| Item | Value |
|---|---|
| URLs in tests | Relative paths in `page.goto` (each project sets `baseURL`) |
| Browsers | Generated by `playwright.config.ts`. Don't edit the config to add or remove an app |

Do not write anything into `test-results/`: Playwright wipes it on every run and it is git-ignored.

---

## 🎯 STEP 1: Read User Story

**Prompt:**

```
I need to start a new testing workflow for {STORY_ID}. First state the resolved run
configuration (story file, app, base URL, seed, Chromium project, plan, test directory,
branch, target repo) and the app's agentNotes.

Then read the user story from:
{STORY_FILE}

Summarize the key requirements, acceptance criteria, and testing scope.
```

You do not check or touch the target repo. Delivery (and its bootstrap requirement) is a
separate human step with `./push-artifacts.sh`; `run-stories.sh` already verifies bootstrap
up front for batch runs.

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
4. Screenshots are optional and only to aid your own analysis; keep them out of the
   delivery (do not save them under the app folder). The QA results report is produced by
   CI, not here.
5. Document your findings:
   - Test execution results for each scenario
   - Any UI inconsistencies or unexpected behaviors
   - Missing validations or bugs discovered
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
6. Do NOT run a cross-browser pass. To save tokens, the agent generates and heals on
   {CHROMIUM_PROJECT} only. The suite still runs on all of the app's browser projects in
   CI (the target repo's workflow runs `npx playwright test`); the agent does not heal
   those here.
7. Document:
   - Initial test results (pass/fail count) on {CHROMIUM_PROJECT}
   - Healing activities performed
   - Final test results after healing on {CHROMIUM_PROJECT}
   - Any tests that couldn't be auto-healed
```

**Expected Output:**

- All automation tests executed
- Failing tests identified and healed using test-healer agent
- Healed test scripts updated in {TEST_DIR}
- Final stable test execution results on {CHROMIUM_PROJECT} (cross-browser is left to CI)
- Summary of healing activities performed

---



## 🛑 STEP 6: Stop for Human Review (do NOT deliver)

**This is the end of the agent's work.** Do NOT open a pull request, do NOT run
`./push-artifacts.sh`, do NOT use local `git` or any GitHub MCP, and do NOT write a report
file. The QA **report is generated by CI** (the target repo's
`.github/workflows/playwright.yml`) once the suite is delivered — not by the agent.

Delivery is a separate, human-initiated step: after reviewing the generated test code, a
human runs `./push-artifacts.sh {APP} {STORY_ID}` to sync the story, plan and tests onto
branch `{BRANCH}` of `{TARGET_REPO}` and open the PR into `{TARGET_BRANCH}`.

**Prompt:**

```
The test suite is written and healed on {CHROMIUM_PROJECT}. Stop here for human review —
do not deliver. End with a short Markdown summary as your final message (no file written):
- Story, application and base URL tested
- Acceptance criteria covered, and the test files created in {TEST_DIR}
- Local Chromium result from Step 5 (pass/fail count) and any healing performed
- Any defects or notable observations found during exploration (Step 3)
- Any "Unattended decisions" made (batch mode only)
- A reminder that a human delivers with: ./push-artifacts.sh {APP} {STORY_ID}
  (full cross-browser results are then produced by that repo's CI)

Do not create {APP_DIR}/reports/... and do not run any delivery command.
```

**Expected Output:**

- The healed test suite left in `{TEST_DIR}`, ready for a human to review
- A concise summary as the final message (no file written, no PR)
- No delivery performed — that is the human's next step with `./push-artifacts.sh`
