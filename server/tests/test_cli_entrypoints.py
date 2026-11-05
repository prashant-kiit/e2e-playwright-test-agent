"""Every `python -m` command actually starts. A structural test, by necessity.

The whole suite calls these CLIs by invoking `main(argv)` **after** the module
has been imported, which is the right way to test what they do -- it reaches
the fixtures' database and the fixtures' store, and a subprocess would reach
neither. It also cannot see the one failure mode that belongs to running them
as modules: `if __name__ == "__main__": main()` executes during import, so a
function `main` reaches must already be bound by the time that line runs.

P5-15 shipped `app/accounts/__main__.py` with that block above
`_purge_tenant`, so `python -m app.accounts purge-tenant` raised `NameError`
while every test of it passed. The command was the only documented path to
story 32.

Two tests per entry point, and the split matters. The subprocess `--help` run
catches breakage at *import* -- a circular import, a typo in a module-level
statement -- and is the cheap half. It does **not** catch the bug above:
`--help` exits inside argparse before any handler is referenced, so the module
runs and exits 0 with the defect in place. What catches that is an AST check
that the entry block is the last top-level statement, which is the invariant
itself rather than a symptom of it.

One test per command rather than a loop over a list, so a failure names the
command in its own id.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]

# Every module in the tree with a `__main__.py`, discovered rather than listed:
# a CLI added later is covered without anybody remembering this file.
ENTRYPOINTS = sorted(
    f"app.{path.parent.relative_to(SERVER_DIR / 'app').as_posix().replace('/', '.')}"
    for path in (SERVER_DIR / "app").rglob("__main__.py")
)


def test_the_entrypoints_were_found_at_all():
    """A discovery that found nothing would make every test below vacuous."""
    assert set(ENTRYPOINTS) >= {"app.accounts", "app.artifacts", "app.delivery"}


@pytest.mark.parametrize("module", ENTRYPOINTS)
def test_the_module_runs_as_a_module(module):
    """`--help` exits 0 without opening a database or a store.

    What this catches is import-time breakage: a name used before it is bound,
    a circular import, a typo in a module-level statement. What it deliberately
    does not do is exercise behaviour -- that is every other CLI test's job,
    and doing it here would mean a subprocess with no fixtures.
    """
    done = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=SERVER_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert done.returncode == 0, done.stderr
    assert "usage:" in done.stdout


@pytest.mark.parametrize("module", ENTRYPOINTS)
def test_the_entry_block_is_the_last_thing_in_the_file(module):
    """`if __name__ == "__main__":` must come after everything it can reach.

    This is the assertion that actually catches the P5-15 bug, and the reason
    it is structural rather than behavioural is worth writing down, because the
    obvious behavioural test does **not** work: `--help` -- on the parser or on
    a subcommand -- exits inside argparse before any handler is referenced, so
    the module runs and exits 0 with the defect in place. Catching it by
    running the command would mean dispatching a real `purge-tenant`, which
    needs a database the subprocess cannot be given.

    So the invariant is checked where it lives: the entry block is the last
    top-level statement, which makes "a name used before it is bound" not a
    thing this file can express.
    """
    path = SERVER_DIR / module.replace(".", "/") / "__main__.py"
    tree = ast.parse(path.read_text())

    entries = [
        i
        for i, node in enumerate(tree.body)
        if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test)
    ]
    assert len(entries) == 1, f"{module} has {len(entries)} entry blocks"
    assert entries[0] == len(tree.body) - 1, (
        f"{module}'s `if __name__ == \"__main__\"` block is followed by "
        f"{len(tree.body) - 1 - entries[0]} more top-level statement(s). It "
        f"runs during import, so anything defined after it is unbound when "
        f"the command dispatches -- which is how `python -m app.accounts "
        f"purge-tenant` shipped raising NameError with a green suite."
    )
