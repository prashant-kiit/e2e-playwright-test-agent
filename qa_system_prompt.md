# End-to-End QA Workflow with Natural Language

## Workflow Overview

This prompt guides you through a complete 7-step QA workflow using MCP servers and AI agents to go from user story to automated test scripts delivered as a pull request.

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

1. The kick-off prompt names the active story (e.g. `Active story: SCRUM-201`).
2. If no story is named, ask the user which story to run. Don't guess. (Unattended: end the run with an error.)
3. Find the one file matching `apps/*/user-stories/{STORY_ID}-*.md`. The folder it sits in is the app. If there is no match, or more than one, stop and ask (unattended: end the run with an error).
4. Read `apps/{APP}/app.json`.
5. State the resolved values at the start of Step 1 so the user can catch a wrong pick.

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
| `{RUN_ID}` | Unattended only: the `Run-ID:` line in the kick-off prompt (e.g. `20261004-180531-saucedemo`). Empty for interactive runs |

Rules that follow from this layout:
- The agent generates and heals on `{CHROMIUM_PROJECT}` only (token saving). `npx playwright test {TEST_DIR}` (no `--project`) runs all 4 of the app's projects; that full run is for CI, not the agent.
- Always pass `project: "{CHROMIUM_PROJECT}"` and `seedFile: "{SEED}"` to `planner_setup_page` and `generator_setup_page`. Left out, they use the first project (whichever app sorts first) and create a default seed file.
- Locate elements the way `app.json` `locators` says, and follow every `agentNotes` entry in every step.

To add a story: drop `<STORY_ID>-<slug>.md` into `apps/<app>/user-stories/`. To add an app: copy `apps/_template/` to `apps/<new-app>/`, fill in `app.json`, write `seed.spec.ts` and the stories. Nothing else changes.

### Unattended (batch) runs

`run-stories.sh` starts one headless session per story, several at once, with `Mode: unattended` and a `Run-ID:` line in the kick-off prompt. All stories in a batch belong to the same app, so parallel runs share one target repo. In that mode:

1. **Never ask the user.** Nobody can answer, and asking ends the session. Wherever this prompt says "stop and ask", apply the default below and record it under "Unattended decisions" in the report.
   - Story file not found, or more than one match: end the run with a one-line error. Do nothing else.
   - Anything else unclear: make the most conservative choice that lets the run finish, and note it.
2. **The run-id makes a rerun safe and traceable.** The script wipes this story's old generated files before restarting it, so you always start clean (never merge leftovers from an earlier attempt). Put a `**Run-ID:** {RUN_ID}` line in the PR body.
3. **Reuse the stable branch `{BRANCH}` — do not add a run-id or timestamp suffix.** In step 7: if `{BRANCH}` already exists, update it to match the current artifacts (push the files onto it) rather than creating a new branch; if an open PR from `{BRANCH}` already exists, update that PR instead of opening a second one. This keeps one branch and one PR per story across reruns.
4. **Other stories are running in this repo at the same time.** Write only your own story's files (`{PLAN_FILE}`, `{TEST_DIR}`). Never edit `playwright.config.ts`, any `app.json`, any seed or another story's files, and never delete other folders (e.g. `test-results/`, `runs/`).
5. Playwright output goes to the per-story folder in `QA_RUN_DIR` automatically. Run the commands exactly as written in the steps.
6. Step 7 runs without approval prompts (the batch script allows the GitHub MCP tools).
7. End with a short summary as your final message: story, app, Chromium test counts, open defects, and the PR URL (or the reason delivery didn't happen). The batch script reads the PR URL from this to mark the story delivered.

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
report, branch, target repo) and the app's agentNotes. Then read the user story from:
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



## 📊 STEP 6: Summarize Results for the Pull Request

The QA **report is generated by CI**, not by the agent. CI (the target repo's
`.github/workflows/playwright.yml`) runs the tests on every browser project and writes a
pass/fail/flaky/skipped table to the run's Job Summary, plus the HTML report artifact. So do
NOT write a report file in this repo. Instead, prepare a short summary to use as the PR body.

**Prompt:**

```
Prepare a short Markdown summary (for the pull request body, not a file) covering:
- Story, application and base URL tested
- Acceptance criteria covered, and the test files created in {TEST_DIR}
- Local Chromium result from Step 5 (pass/fail count) and any healing performed
- Any defects or notable observations found during exploration (Step 3)
- Any "Unattended decisions" made (batch mode only)
- A line noting that full cross-browser results are produced by CI (the run's Job Summary
  and the playwright-report artifact)

Do not create {APP_DIR}/reports/... — there is no agent-written report any more.
```

**Expected Output:**

- A concise PR-body summary held in the session (no file written)
- Clear statement that authoritative results come from CI

---



## 🚀 STEP 7: Open a Pull Request in the Target Repository

**Target repository:** `{TARGET_REPO}`, branch `{TARGET_BRANCH}`, both from `{APP_DIR}/app.json`

**Prompt:**

```
Now I need to deliver the test artifacts to the target repository using the GitHub MCP
server ({TARGET_REPO}). Do not use local
git commands and do not commit to this workspace repository.

1. Check whether the target repository has any commits.
   If it is empty, first push one bootstrap commit directly to {TARGET_BRANCH} containing these
   workspace files at the same paths:
   - package.json
   - package-lock.json
   - playwright.config.ts
   - .gitignore
   - .github/workflows/playwright.yml
   - {APP_DIR}/app.json
   - {SEED}
   Commit message: "chore: bootstrap Playwright project"
   If that push fails because {TARGET_BRANCH} now exists (a parallel run bootstrapped it
   first), skip the bootstrap and continue.

2. If {BRANCH} doesn't exist, create it from {TARGET_BRANCH}. If it already exists
   (e.g. a rerun of this story), reuse it: push the current artifacts onto it, and if an
   open PR from it already exists, update that PR instead of opening another.

3. Push these files to that branch, at the same paths as in the workspace:
   - {STORY_FILE}
   - {PLAN_FILE}
   - {TEST_DIR}*.spec.ts
   (No report or screenshots: the results report is generated by CI.)
   Shared files: also push playwright.config.ts, {APP_DIR}/app.json and {SEED} if they
   are missing on {TARGET_BRANCH} or differ from the workspace copies (skip whatever the
   bootstrap just pushed). Never push another app's folder.
   Follow any delivery instructions in app.json agentNotes (e.g. legacy paths to delete). The target repo's CI runs
   `npx playwright test`, so it needs the app's browser projects and seed.
   Commit message:
   "feat(tests): Add complete test suite for {STORY_ID} {STORY_TITLE}

   - Add user story documentation
   - Add comprehensive test plan with all scenarios
   - Add automated test scripts
   - Include happy-path and key negative tests

   Resolves {STORY_ID}"

4. Open a pull request from {BRANCH} into {TARGET_BRANCH} titled "{PR_TITLE}", using the
   Step 6 summary as the body. Note in it that CI generates the authoritative results
   report (the run's Job Summary and the playwright-report artifact).

5. Provide a summary of what was pushed and the pull request URL
```

**Expected Output:**

- Bootstrap commit on {TARGET_BRANCH} of {TARGET_REPO} (first run against that repo only)
- Branch {BRANCH} with the story, plan and tests (plus shared config/seed if they changed)
- Pull request opened into {TARGET_BRANCH}
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
are stable and passing on {CHROMIUM_PROJECT}. Do NOT do a cross-browser pass: to save
tokens the agent heals on Chromium only; the target repo's CI runs the suite on all
projects. Document healing activities.

STEP 6 - SUMMARIZE FOR THE PR:
Do not write a report file: the results report is generated by CI. Prepare a short Markdown
summary (ACs covered, test files, local Chromium result, defects, unattended decisions) to
use as the pull request body.

STEP 7 - OPEN A PULL REQUEST:
Using the GitHub MCP server, deliver the artifacts to {TARGET_REPO} (the active app's repo)
as described in Step 7 of qa_system_prompt.md: bootstrap {TARGET_BRANCH} if the repo is empty,
push the user story, test plan and tests (and shared config/seed if changed) to
branch {BRANCH}, and open a pull request into {TARGET_BRANCH} titled "{PR_TITLE}" whose
body is the Step 6 summary.

Execute this complete workflow and provide status updates after each step.
```
