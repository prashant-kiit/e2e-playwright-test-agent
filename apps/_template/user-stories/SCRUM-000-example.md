# User Story: SCRUM-000 - Feature Area Title

<!-- File name pattern: <STORY_ID>-<slug>.md. The slug names the generated test folder (tests/<slug>/),
     plan, report and branch. Story IDs must be unique across all apps.
     Keep it LEAN to save tokens: ~2 acceptance criteria (one happy path + one key negative/behavior).
     Each AC drives exploration, test generation and healing, so fewer ACs = fewer tokens. -->

## Story Title
As a <role>, I want <capability> so that <benefit>.

## Story Description
What the feature does, in a couple of sentences. Note the trimmed scope.

## Application URL
https://your-app.example.com (pages: `/...`)

## Test Credentials
None required, or list them here.

## Acceptance Criteria

### AC1: <Main success flow> (happy path)
- GIVEN ...
- WHEN ...
- THEN ...

### AC2: <Most important negative / validation / behavior> (key negative)
- GIVEN ...
- WHEN ...
- THEN ...

## Business Rules
1. The one or two rules that matter for the ACs above.

## Technical Notes
- Use Playwright. Locate elements the way this app's app.json "locators" says (list the test IDs/roles the ACs need)
- Any timing or data quirk the agent must know
- The agent generates and heals on Chromium only to save tokens; the target repo's CI runs the suite on all browser projects

## Definition of Done
- [ ] Acceptance criteria have test cases
- [ ] Automated test scripts created and passing on Chromium
- [ ] Test results documented
- [ ] Code committed to repository
