"""The apps/<app>/ layout, staged as a worktree.

**Deleted with the mount in P3-08.** It exists for the span of the flip: the
tracked tree is root-relative from P3-02, but while `apps/` is still
authoritative a target's content lives under `apps/<app>/` and its infra comes
from the templates in the server package. Nothing else in the system knows about
the monorepo layout any more, and this is the one place that still does.

Staging is a copy into a temporary directory rather than a second enumeration
with a different mapping, because a second mapping is a second thing that can
disagree about what the product versions -- which is the drift P3 exists to
remove. What comes out is a worktree of exactly the shape hydrate builds, so the
same scan, the same parity check and the same commit path run over it.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import config
from .delivery.render import (
    TRACKED_APP_FILES,
    TRACKED_APP_TREES,
    read_target_config,
    write_infra,
)


def app_dir(app: str) -> Path:
    return config.repo_root() / "apps" / app


@contextmanager
def staged_tree(app: str) -> Iterator[Path]:
    """`apps/<app>/` plus the rendered infra set, as a worktree root.

    The configuration the generated entry is rendered from still comes from
    app.json, because this runs while that file is what there is.
    """
    cfg = read_target_config(app)
    tmp = Path(tempfile.mkdtemp(prefix="qa-monorepo-"))
    try:
        root = tmp / "worktree"
        root.mkdir()
        write_infra(root, cfg)
        base = app_dir(app)
        for rel in TRACKED_APP_FILES:
            if (base / rel).is_file():
                shutil.copyfile(base / rel, root / rel)
        for tree, _pattern in TRACKED_APP_TREES:
            if (base / tree).is_dir():
                shutil.copytree(base / tree, root / tree, dirs_exist_ok=True)
        yield root
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
