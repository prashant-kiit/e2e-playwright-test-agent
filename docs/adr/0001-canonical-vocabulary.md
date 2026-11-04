# Canonical vocabulary: target, project, spec

`GLOSSARY.md` resolves three words this codebase uses for more than one thing,
and the resolutions deliberately disagree with some of the spellings already in
the code. Recording them here so the next reader does not "fix" the glossary to
match the columns.

**"Target", not "app".** The two have always named one concept — `targets.app`
is the slug, `AppLock` is keyed by `target_id`, and `repo.py` says "app (target
N) already has a live run". Target won because it is the row, the lock's real
key and the thing a revision belongs to; "app" survives only as a column name,
a class name and the delivery CLI's argument. Those spellings are legacy, not a
second concept, and renaming them is a migration nobody has asked for yet.

**"Project" stays the tenant's grouping of targets; a browser is a "browser
project".** Playwright has the stronger claim on the bare word, and in a
Playwright repo that is an argument for giving it up. We kept it anyway: it is
the `projects` table, it is what the portal shows, and it is what an operator
says. The cost is that prose about Playwright has to qualify every use, which
`render.py` already does.

**"Spec" alone is banned.** `specs/` holds markdown test plans while
`*.spec.ts` are generated test files, so the generator writes `// spec:
specs/...` into a spec file about something that is not one. Rather than pick a
winner we took the word out of service: **test plan** for the markdown, **spec
file** for the generated test. The directory name is left alone because
renaming it is a tree change, which is a revision, and the ambiguity is cheaper
than the churn — but the directory name is not evidence of what the word means.

Architectural decisions live in `.claude/harness/DESIGN.md` §14, not here. This
ADR exists because that log covers what the system does and not what its parts
are called.
