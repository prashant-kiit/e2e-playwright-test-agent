# A delivery branch is scoped by target, not by story alone

#51 found that `resolve_story` built the delivery branch as
`qa/{story_id}-{slug}` from the story's filename alone, and asked for a
decision before implementing, because the two candidate fixes are not
equivalent and one of them forbids a layout nobody has said is wrong.

**Decision.** The target's slug is a segment of the branch name:
`qa/{app}/{story_id}-{story-slug}`. `resolve_story` requires `app` rather than
defaulting it, and `targets.target_repo` stays unconstrained — **two targets of
one tenant may point at the same repo and the same base branch on purpose**.

**What was broken.** Nothing constrains `targets.target_repo` or
`targets.target_branch`, and a story id is resolved inside each target's own
tracked tree, so two targets of one tenant can each hold
`user-stories/SCRUM-101-checkout.md`. Delivering both put them on one branch.
`push.py` appends and never force-pushes (DESIGN.md decision 10, which is there
to protect PR review threads), so the second delivery wrote the second target's
whole materialized tree as a commit on top of the first's. Both targets
recorded `delivered_sha`, one PR carried a mixture of two suites, nothing
errored, and `check` answers from Postgres so neither target's status revealed
it. Tenant isolation was never involved: this is isolation *between two targets
of one tenant*, which the delivery path did not model.

**The alternative, and why not.** Make `(tenant_id, target_repo,
target_branch)` unique and refuse the overlap at save. It is cheaper — no
existing branch name changes — but it forbids one repo holding several apps'
suites, which is a plausible customer layout and one this system is otherwise
happy to serve: a repo per app is a choice, not a requirement, and the
constraint would turn it into one on no evidence that the sharing is a mistake.
A configuration refusal is also the worse failure to be wrong about: it blocks
a setup somebody wanted, at save time, with no way around it but a second repo.

**What the decision costs**, stated plainly because it is a real cost and it is
paid by work already delivered: an already-delivered story's branch name
changes, so its next delivery pushes to a new branch and opens a **second PR**
rather than updating the first. The old branch and its PR remain, and nothing
cleans them up. That is cheapest now, while the delivered set is small, and it
gets more expensive every time a story is delivered — which is the argument for
taking it in this change rather than recording it as a follow-up.

**One consequence worth naming.** The slug is now part of a git ref, so a slug
git cannot spell is a target that can be created and never delivered.
`target_config.clean_app_slug` refuses one at the write path (lower-cased and
stripped first, like a tenant's slug), and
`delivery.render._assert_branch_safe` asks the same question again at the read
path for rows saved before the check existed. It **refuses** rather than
sanitising: replacing the offending characters would map two distinct slugs
onto one branch name, which is the collision this ADR is about, reintroduced by
its own fix.

Two things follow from that, and neither is comfortable enough to leave
implicit:

- **The read-path check asks only what git asks**, which is why upper case is
  accepted there while the write path lower-cases it. `targets.app` is
  deliberately not editable (`repo.update_target_config`), so a row saved
  before this check cannot be repaired in place: refusing a spelling git is
  happy with would have left such a target permanently undeliverable with no
  remedy but creating a new one. A slug git genuinely refuses — a space, a
  `..` — is still stuck in exactly that way, and the remedy is a new target.
  No migration surveys or rewrites existing slugs; lower-casing them in place
  could collide with `uq_targets_tenant_id_app`, and a migration that can fail
  on a customer's data to tidy a name is the worse trade.
- **The refusal reaches a run, not only a delivery.** The agent's `{BRANCH}`
  comes from the same function, so a target whose slug cannot be a ref fails
  at the run's first step. That is the right direction — such a run would
  produce a suite nobody can deliver, and it fails before the tokens are spent
  rather than after — but it is a failure mode this ticket did not contemplate,
  so it is asserted in `tests/test_agent_prompts.py` rather than left to be
  discovered.

The one caller that used to rely on the `app=""` default — the orchestrator,
rendering `{BRANCH}` into the agent's prompt — now passes the run's target, so
the name the agent is told and the name delivery pushes to cannot drift apart.
The default is gone rather than kept for convenience: a caller that passed
nothing would silently get the colliding shape back.
