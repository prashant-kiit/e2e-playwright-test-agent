"""Reading the source as the structural tests read it.

Two phases now assert things about the *code* rather than about behaviour -- P3's
"the mount is gone" (tests/test_no_repo_mount.py) and P4's "no GitHub credential
is readable from a sandbox" (tests/test_sandbox_credentials.py). Both need the
same distinction, and it is a subtle one worth having in one place: what the code
*does*, not what its prose *says*.

Explaining in a docstring that `repo_root()` was deleted and why, or that the
delivery package re-exports lazily so `GITHUB_PAT` stays out of a sandbox's
import graph, is exactly the comment a future reader needs. A *call* to the
first and a *read* of the second are the things to catch.
"""

from __future__ import annotations

import ast
from pathlib import Path


def code_of(path: Path) -> str:
    """A module's code with its comments and docstrings removed.

    Parsing and unparsing drops comments; the walk drops docstrings.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def code_lines(text: str) -> str:
    """A Dockerfile or compose file with its comment lines removed.

    The same distinction `code_of` draws for Python, for the files where the
    comment explaining a credential decision names the credential.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
