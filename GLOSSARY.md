# QA Harness

An agentic QA harness. An operator writes a user story for a web application;
the harness drives an agent that explores the live app, plans, generates and
heals a Playwright test suite, and stops for human review. A human then
delivers the suite to the customer's own repository, where CI runs it.

## Language

### Tenancy and ownership

**Tenant**:
A customer of the harness. The boundary of all ownership: no row is visible
outside the tenant that owns it.
_Avoid_: Organization, account, workspace, customer (in code)

**Operator**:
A person who drives the harness through the portal. Belongs to exactly one
tenant and holds one role there.
_Avoid_: User (in prose), admin, tester, QA engineer
_But_: the table is `users`, the model is `User`, and the portal's own panel
and route are `/users` — the spelling an operator expects to click and the one
the schema already uses. Those are legacy-and-interface spellings of this
concept, not a second concept, exactly as `targets.app` is for **Target**
(ADR 0001). Prose says operator; columns, routes and UI labels say user.

**Onboarding**:
Creating a tenant together with its first admin. One operation, because a
tenant with no admin can never be administered: it is refused on the way out
(the last admin cannot be removed) and so is never created on the way in. It
is an operator-run command rather than a portal action — see ADR 0002.
_Avoid_: Signup, registration, provisioning, tenant creation (alone)

**Project**:
A tenant's grouping of targets, used to organize work. Carries no
configuration of its own.
_Avoid_: Folder, group, workspace. Never use "project" for a Playwright
browser project — say **browser project**

**Target**:
One web application the harness tests, together with the configuration for
testing it: where it lives, which repository receives its tests, and how to
address its elements. The unit a run, a revision and a lock all belong to.
_Avoid_: App, application under test, SUT, site. "App" is a legacy spelling of
this term, not a second concept: it survives in the `app` slug column, in
`AppLock` and in the delivery CLI's argument

**Browser project**:
One browser configuration a suite is executed against (Chromium, Firefox,
WebKit, mobile Chrome). Playwright's term for it is "project", which is why it
is always qualified here.
_Avoid_: Project (unqualified), browser, platform

### What the operator writes

**User story**:
An operator-authored description of behaviour to be tested, in markdown,
identified by a story ID. Exactly one is the input to a run.
_Avoid_: Ticket, issue, requirement, feature, spec

**Acceptance criterion**:
One checkable statement of expected behaviour within a user story. The unit a
test plan's scenarios and the generated suite's groupings follow.
_Avoid_: AC (in prose), requirement, assertion

**Seed**:
The steps that bring the application to the starting state a test assumes —
signing in, for example. Shared starting state, not a test.
_Avoid_: Setup, fixture, bootstrap, login helper

### What the agent produces

**Test plan**:
The agent's markdown account of what it intends to test: scenarios, their
steps, their expected results, and the stable locators it found while
exploring the live application.
_Avoid_: Spec, plan file, design, strategy

**Test suite**:
The generated Playwright tests for one user story.
_Avoid_: Scripts, specs, test cases

**Spec file**:
One file of the test suite. Only ever a generated test file, never a test
plan. The `specs/` directory holds test plans, so its name is a legacy
spelling and not a guide to the word.
_Avoid_: Spec (unqualified), test script

**Artifact**:
Evidence a run produced and the harness keeps: traces, videos, screenshots,
reports, logs. Stored as blobs, never part of the tracked tree.
_Avoid_: Output, result, attachment, evidence

### Execution

**Run**:
One attempt at one user story for one target. Carries its own status and
progress, holds its target's lock while live, and produces revisions and
artifacts.
_Avoid_: Job, session, execution, build

**Step**:
One of the five stages of a run — read story, plan, explore, generate, heal —
in fixed order. Also the checkpoint boundary: a run pauses, resumes and
commits only between steps.
_Avoid_: Stage, phase, task

**Live run**:
A run that has not reached a terminal status, and therefore still holds its
target's lock. A paused run is live.
_Avoid_: Active run, open run, in-flight run

**Run mode**:
Whether a run tests the whole application or only the acceptance criteria that
changed in the user story since the last tested version.
_Avoid_: Scope, strategy

**Agent session**:
The agent's conversation for one run, resumable across a pause. Does the
reading, the exploring and the stopping itself, and delegates planning,
generation and healing to sub-agents.
_Avoid_: Claude session, conversation, chat

**Sub-agent**:
A single-purpose agent a session delegates one step to: the planner, the
generator or the healer. Sub-agents hand work to each other only through files
in the worktree.
_Avoid_: Subagent (in prose), worker, tool, helper

**Sandbox**:
The isolated place one run executes in, created for that run and destroyed
with it. Holds no store credential, no GitHub credential, and no route out
except an allowlist built from its target.
_Avoid_: Container, runner, executor, VM

**Sandbox attempt**:
Which sandbox of a run is the current one. A run may go through several -- a
pause destroys one and a resume creates the next -- so the run-scoped token
names the attempt it was minted for, and a destroyed sandbox's token
authorizes nothing. Not a **Run**, which this glossary already calls "one
attempt at one user story", and not a step's retry count.
_Avoid_: Attempt (bare), generation, epoch, incarnation

**Target lock**:
The guarantee that one target has at most one live run. Held as a lease, so a
run whose sandbox died loses it by expiry rather than holding it forever. A
second run on a locked target is refused, never queued.
_Avoid_: App lock, mutex, semaphore, queue

**Reaper**:
The sweep that frees targets whose run died, fails runs that outlived their
limits, and prunes what has aged out.
_Avoid_: Janitor, cleaner, GC, cron

### The tracked tree

**Tracked tree**:
Everything about a target that is versioned: its user stories, test plans,
seed, test suite and test infrastructure. Its configuration is not part of it.
_Avoid_: Working tree, repo, files, workspace

**Revision**:
An immutable, numbered snapshot of a target's tracked tree, attributed to
whoever produced it. The authority on what the tree contains; a revision that
changed nothing is never committed.
_Avoid_: Commit, version, snapshot

**Head revision**:
A target's latest revision: what a run hydrates from and what delivery pushes.
_Avoid_: Latest, tip, HEAD, current

**Worktree**:
A run's own materialization of the head revision, which the agent reads and
writes, and which is deleted when the run ends. Not a git worktree.
_Avoid_: Checkout, workspace, sandbox dir

**Hydrate**:
To build a run's worktree from a revision.
_Avoid_: Materialize (reserved for delivery), checkout, clone, restore

**Ingest**:
To commit what a step changed in the worktree as the next revision. Runs at
each step boundary; a failure here fails the run, because truth has already
moved.
_Avoid_: Commit (as a verb), save, sync, upload

### Going outward

**Target repo**:
The customer's own repository that receives a target's delivered tests and
runs them in its CI. The harness copies outward to it and never reads back. Always said in full:
shortened to "target" it would name the application under test instead,
which is a different thing.
_Avoid_: Remote, upstream, customer repo, test repo

**Delivery**:
The human-initiated step that pushes a reviewed revision to the target repo as
a branch and a pull request. Never part of a run, and never done by the agent.
_Avoid_: Push, deploy, publish, release

**Bootstrap**:
The first delivery to a target repo, which puts the test infrastructure there
before any suite depends on it.
_Avoid_: Init, setup, scaffold

**Credential**:
A target's own access to its target repo, supplied by the customer and used
only at delivery time. Never reaches a sandbox.
_Avoid_: PAT, token, secret, key

**Results report**:
The pass/fail account of a delivered suite, produced by the target repo's CI.
The harness never produces it.
_Avoid_: Report (unqualified), QA report, test results
