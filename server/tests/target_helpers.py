"""Creating a target now means supplying its configuration.

P3 moved apps/<app>/app.json into columns on `targets`, validated at the write
path, so `repo.create_target` requires a base URL and a target repo. Most tests
do not care what the configuration says -- only that it is valid -- so they take
it from here rather than repeating five fields each time.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import repo, target_config
from app.models import Target
from app.target_config import TargetConfig
from app.tenancy import current_tenant_id

BASE_URL = "https://demo.example.com"
# What BASE_URL resolves to for the write path's public-address check (P4, §6).
# A documentation-range address would be refused -- `is_global` excludes it --
# so this is a plainly public one.
BASE_URL_ADDRESS = "93.184.216.34"
TARGET_REPO = "o/r"
LOCATORS = "data-testid attributes: page.getByTestId('...')"
AGENT_NOTES = ("The seed opens the home page logged out.",)

# The same configuration as a detached value, for the fixtures that need to
# render the generated infra entries without a database -- and so the tree a
# fixture commits is the tree hydrate would render from the row it created.
CONFIG = TargetConfig(
    app="demo",
    name="Demo",
    base_url=BASE_URL,
    locators=LOCATORS,
    agent_notes=AGENT_NOTES,
    target_repo=TARGET_REPO,
    target_branch=target_config.DEFAULT_BRANCH,
)


def public_resolver(host: str) -> list[str]:
    """The resolver the fixtures pass to the write path.

    P4 made a target's base URL resolve to a public address at save time, and no
    test may depend on real DNS: `demo.example.com` resolves nowhere, so without
    this every fixture that creates a target would be refused. Any host is
    answered with one public address, because what these tests are about is the
    target, not the resolution -- the resolution itself is tested in
    tests/test_egress.py and tests/test_target_config.py.
    """
    return [BASE_URL_ADDRESS]


def create_target(
    session: Session,
    project_id: int,
    app: str = "demo",
    name: str = "Demo",
    **config,
) -> Target:
    """A target with valid configuration; `config` overrides any field.

    `resolve` is passed through, so a test about resolution can supply its own
    table while every other test gets a resolver that says "public".
    """
    config.setdefault("resolve", public_resolver)
    return repo.create_target(
        session,
        project_id=project_id,
        app=app,
        name=name,
        **{
            "base_url": BASE_URL,
            "target_repo": TARGET_REPO,
            "locators": LOCATORS,
            "agent_notes": list(AGENT_NOTES),
            **config,
        },
    )


def target_body(app: str = "demo", name: str = "Demo", **config) -> dict:
    """The JSON body `POST /projects/{id}/targets` takes, with valid config."""
    return {
        "app": app,
        "name": name,
        "base_url": BASE_URL,
        "target_repo": TARGET_REPO,
        "target_branch": "master",
        "locators": LOCATORS,
        "agent_notes": list(AGENT_NOTES),
        **config,
    }


# What the P3 migration's backfill leaves on a row that existed before it: a
# placeholder target repo and no base URL. Importing a real configuration over
# this is the cutover's job, so tests of the cutover start from exactly here.
BACKFILL = {
    "base_url": "",
    "locators": "",
    "agent_notes": [],
    "target_repo": target_config.PLACEHOLDER_REPO,
    "target_branch": target_config.DEFAULT_BRANCH,
}


def backfilled_target(
    session: Session, project_id: int, app: str = "demo", name: str = "Demo"
) -> Target:
    """A target as the migration's backfill leaves it: unconfigured.

    Built straight through the ORM rather than through `repo.create_target`,
    which validates: the point is a row whose configuration the write path would
    *refuse*, which is what every pre-cutover target is.
    """
    target = Target(
        tenant_id=current_tenant_id(), project_id=project_id, app=app, name=name, **BACKFILL
    )
    session.add(target)
    session.commit()
    session.refresh(target)
    return target
