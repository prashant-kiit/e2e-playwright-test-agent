# End-to-End QA Workflow with Natural Language

## Workflow overview

Five steps take a user story to a healed, automated test suite: read the story, plan,
explore, generate, heal. The portal's orchestrator drives them, one headless Claude Code
session invocation per step, carrying the session across steps so what step 3 learned
about the app survives into step 4. **The agent stops after step 5 for human review.** It
does not deliver: an operator reviews the suite in the portal and approves the delivery,
which opens the pull request in the target repo.

**This document is reference, not a prompt.** The prompt the agent receives for a step is
`steps/_context.md` (the resolved run configuration) followed by `steps/<n>-<name>.md` (the
step's instructions), with every placeholder substituted by the orchestrator. The agent
never reads this file and never resolves anything itself. It is here so a maintainer can
see what the agent is asked to do, and the portal shows it on the Prompts page.

Every run works on **one active story**, for **one target**, in **one worktree**.

---

## The run configuration

A target's configuration lives in Postgres, on its `targets` row — `base_url`, `locators`,
`agent_notes`, `target_repo`, `target_branch` — and its tree lives in content-addressed
blobs indexed by its head `revision`. Before a run's first step the orchestrator
**hydrates** that revision into a per-run worktree and renders the generated files from the
row; at each completed step boundary it **ingests** the worktree as the next revision; when
the run ends it deletes the worktree. The agent's working directory is that worktree.

A worktree holds exactly one target, at its root:

```
<worktree>/
├── seed.spec.ts                     # brings the app to the state every session starts from
├── user-stories/<STORY_ID>-<slug>.md
├── specs/                           # generated: test plans
├── tests/<slug>/                    # generated: test suites
├── playwright.config.ts             # GENERATED from the target row; edits are discarded
├── package.json, package-lock.json, .gitignore
└── .github/workflows/playwright.yml # the customer's CI runs the suite from here
```

There is **no configuration file in the worktree**. `baseURL` is inlined into the generated
`playwright.config.ts`; `locators` and `agent_notes` are injected into the context header.
A configuration change therefore shows up as a tree diff and a new revision, which makes it
as reviewable as a code change.

One target per worktree is also a safety property: a project name or a test path cannot
reach another customer's tests, because no other customer's tests are there.

### Choosing the active story

Nothing to choose. The orchestrator knows the story — it is the run's `story_id` — and
resolves the one `user-stories/<STORY_ID>-*.md` the head revision holds. Zero matches or
two is a hard error before the agent starts, not something for the agent to pick between.

### Placeholders

| Placeholder | Value |
|---|---|
| `{STORY_ID}` | The run's story, e.g. `SCRUM-202` |
| `{STORY_TITLE}` | The title after the ID in the story's first heading |
| `{APP}` | The target's slug, e.g. `practice-target` |
| `{NAME}` | The target's display name |
| `{SLUG}` | The story file name after `{STORY_ID}-`, without `.md`, e.g. `forms` |
| `{STORY_FILE}` | `user-stories/{STORY_ID}-{SLUG}.md` |
| `{SEED}` | `seed.spec.ts` |
| `{PLAN_FILE}` | `specs/{STORY_ID}-{SLUG}-test-plan.md` |
| `{TEST_DIR}` | `tests/{SLUG}/` |
| `{CHROMIUM_PROJECT}` | `chromium` — the generated config is single-target, so project names carry no prefix |
| `{BASE_URL}`, `{LOCATORS}`, `{AGENT_NOTES}` | From the target's row |
| `{TARGET_REPO}`, `{TARGET_BRANCH}` | From the target's row: where an operator later delivers |
| `{BRANCH}`, `{PR_TITLE}` | `qa/{STORY_ID}-{SLUG}`, and `{STORY_ID}: {STORY_TITLE} E2E test suite` |
| `{MODE}` | `full` or `changed` |
| `{RUN_KEY}` | The run's id, e.g. `20261024-180531-saucedemo-a1b2c3` |

`{TARGET_REPO}`, `{TARGET_BRANCH}`, `{BRANCH}` and `{PR_TITLE}` describe where an operator
later delivers the suite. The agent never pushes and never opens a PR.

### Rules that follow from the layout

- The agent generates and heals on `{CHROMIUM_PROJECT}` only, to save tokens.
  `npx playwright test {TEST_DIR}` with no `--project` runs all four projects; that full run
  is for CI, not for the agent.
- Always pass `project: "{CHROMIUM_PROJECT}"` and `seedFile: "{SEED}"` to
  `planner_setup_page` and `generator_setup_page`. Left out, they use the first project and
  create a default seed file.
- Locate elements the way `{LOCATORS}` says, and follow every `{AGENT_NOTES}` entry in every
  step.

### Run contract

Every run is a sequence of headless, unattended sessions. These rules always apply:

1. **Never ask anyone.** There is no human in the session; asking just ends it. Wherever a
   step says "stop" on ambiguity, make the most conservative choice that lets the run finish
   and record it in the final summary under "Unattended decisions".
2. **A rerun is safe.** Each run gets a fresh worktree hydrated from the head revision, so it
   never inherits a previous attempt's half-written files.
3. **The agent does not deliver.** It stops after step 5 with the healed suite in
   `{TEST_DIR}`. An operator reviews it and approves the delivery in the portal.
4. **Write only the active story's files** — `{PLAN_FILE}` and files under `{TEST_DIR}/`.
   `playwright.config.ts` is regenerated before the work is recorded, so editing it changes
   nothing; the seed and other stories' files are not the run's to touch.
5. Playwright output goes to the run directory automatically, through the generated config.
   `test-results/` and `playwright-report/` are run output, swept into the run's artifacts
   and never part of the tree.
6. End with a short summary: story, target, the test files created, the Chromium pass/fail
   count after healing, open defects, and any "Unattended decisions".

### Fixed conventions

| Item | Value |
|---|---|
| URLs in tests | Relative paths in `page.goto` (every project sets `baseURL`) |
| Browsers | `chromium`, `firefox`, `webkit`, `mobile-chrome`, from the generated config |

---

## The five steps

The text the agent receives is in `steps/`. It is not duplicated here: one copy of a prompt
is the only way the copy that runs and the copy a maintainer reads cannot drift.

| Step | Prompt | What it does | What it leaves behind |
|---|---|---|---|
| 1 | [`steps/1-read_story.md`](steps/1-read_story.md) | States the resolved run configuration, reads the story, summarises requirements, acceptance criteria and scope | Nothing on disk — the session log |
| 2 | [`steps/2-plan.md`](steps/2-plan.md) | `playwright-test-planner` explores the app from the seed and writes a plan covering happy paths, negative cases, edge cases, navigation and UI validation | `{PLAN_FILE}` |
| 3 | [`steps/3-explore.md`](steps/3-explore.md) | Executes the plan by hand over the Playwright MCP browser tools, recording what actually happened and which locators worked | Nothing on disk — findings in the session |
| 4 | [`steps/4-generate.md`](steps/4-generate.md) | `playwright-test-generator` turns the plan plus step 3's locators into TypeScript specs, then runs them on Chromium | `{TEST_DIR}/*.spec.ts` |
| 5 | [`steps/5-heal.md`](steps/5-heal.md) | `playwright-test-healer` fixes failures — selectors, waits, assertions — and re-runs until the suite is stable on Chromium | A healed `{TEST_DIR}/` |

Steps 1 and 3 change no tracked file, so they commit no revision: `rev` counts real changes,
not steps. Steps 2, 4 and 5 normally each commit one.

### The subagents

Shipped with the server package under `agent_runtime/agents/` and passed to the CLI inline,
so their names stay bare — `playwright-test-planner`, `playwright-test-generator`,
`playwright-test-healer` — which is how the step prompts invoke them.

### Why the agent stops at step 5

Delivery is an approval, and an approval needs somebody to give it. The operator reviews the
healed suite in the portal and approves the push, which squashes the head revision into one
commit on `{BRANCH}` and opens or updates the PR into `{TARGET_BRANCH}`. Folding that into
the agent would make a token budget the thing that decides what reaches a customer's repo.
