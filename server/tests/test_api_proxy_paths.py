""""Why is this endpoint returning HTML?" -- the two proxy lists, kept honest.

The API's paths sit at the root and **collide with the SPA's client routes**
(`/projects`, `/settings`, `/runs`, ...). Both the nginx config that serves
production and the Vite dev proxy therefore carry an explicit list of path
prefixes to forward to the backend, splitting on `Accept: text/html` so a
full-page navigation gets the SPA and a `fetch` gets JSON.

A path missing from those lists does not 404. It falls through to
`try_files $uri /index.html` and answers **200 with the SPA shell**, which
`api.js` then detects as HTML and raises on -- and a caller that degrades
gracefully (`.catch(() => setUsage(null))`) swallows it and renders nothing at
all. That is exactly how P5-04's quota panel shipped invisible: `/usage` was in
neither list, every one of its 84 frontend tests passed, and the gauges never
appeared in a browser. jsdom cannot see this class of bug, because jsdom has no
proxy.

So the lists are asserted against the one module that names every endpoint.
Built from a list, like `test_compose_stack.py` and `test_sandbox_credentials.py`:
the point is that adding a route to `api.js` and forgetting the proxy is a test
failure rather than a silently blank panel.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_JS = REPO / "web" / "src" / "api.js"
RUN_DETAIL_JSX = REPO / "web" / "src" / "pages" / "RunDetail.jsx"
NGINX_CONF = REPO / "docker" / "nginx.conf"
VITE_CONFIG = REPO / "web" / "vite.config.js"

# A root-relative path in a plain or template string: "/usage", `/runs/${id}`.
_PATH_LITERAL = re.compile(r"""["'`](/[a-zA-Z][a-zA-Z0-9_-]*)""")


def _first_segments(source: str) -> set[str]:
    """The distinct first path segments the source requests, e.g. `/usage`."""
    return {m.group(1) for m in _PATH_LITERAL.finditer(source)}


def _requested_prefixes() -> set[str]:
    """Every API prefix the frontend actually calls.

    `api.js` is the single API layer, plus `RunDetail.jsx`'s `EventSource` --
    which bypasses `api.js` on purpose, because `EventSource` opens its own
    connection and cannot carry the refresh dance.
    """
    return _first_segments(API_JS.read_text()) | {
        p for p in _first_segments(RUN_DETAIL_JSX.read_text()) if p == "/runs"
    }


def _nginx_prefixes() -> set[str]:
    """The alternation in nginx's API `location` block."""
    conf = NGINX_CONF.read_text()
    match = re.search(r"location\s+~\s+\^/\(([^)]+)\)", conf)
    assert match, "the API location block in docker/nginx.conf has changed shape"
    return {f"/{name}" for name in match.group(1).split("|")}


def _vite_prefixes() -> set[str]:
    """The `apiPaths` array in the Vite config."""
    cfg = VITE_CONFIG.read_text()
    match = re.search(r"const apiPaths = \[(.*?)\]", cfg, re.DOTALL)
    assert match, "apiPaths in web/vite.config.js has changed shape"
    return set(re.findall(r'"(/[^"]+)"', match.group(1)))


def test_the_two_proxy_lists_agree_with_each_other():
    """One list is the dev proxy and the other is production. A path in only one
    works on a laptop and breaks when deployed, or the reverse -- both of which
    are worse than failing everywhere."""
    assert _nginx_prefixes() == _vite_prefixes()


@pytest.mark.parametrize("prefix", sorted(_requested_prefixes()))
def test_every_path_the_frontend_requests_is_proxied_in_production(prefix: str):
    assert prefix in _nginx_prefixes(), (
        f"{prefix} is requested by the frontend but is not in docker/nginx.conf's "
        f"API location block, so nginx answers it with the SPA shell (200 + HTML) "
        f"instead of proxying it to the API"
    )


@pytest.mark.parametrize("prefix", sorted(_requested_prefixes()))
def test_every_path_the_frontend_requests_is_proxied_in_development(prefix: str):
    assert prefix in _vite_prefixes(), (
        f"{prefix} is requested by the frontend but is not in web/vite.config.js's "
        f"apiPaths, so the Vite dev server answers it with the SPA shell"
    )


def test_the_extraction_actually_found_the_endpoints():
    """Guard the guard: a regex that silently matched nothing would make every
    assertion above vacuously true."""
    found = _requested_prefixes()
    assert len(found) > 5
    for known in ("/auth", "/projects", "/targets", "/runs", "/usage"):
        assert known in found, f"{known} should have been extracted from api.js"


# --- the inverse guarantee: the internal control plane is not published ---

def test_the_internal_control_plane_is_not_proxied_to_the_public_origin():
    """`/internal/*` is the run-facing API (P5-05) and no browser calls it.

    It is absent from both proxy lists above because nothing in the frontend
    requests it -- which makes its absence an accident of how those lists are
    derived rather than a decision. This is the decision.

    A sandbox reaches these routes by the API's name on the internal Docker
    network, which has no default route; publishing them through the portal's
    origin would put the run-facing surface on the public internet with a
    bearer check as the only thing in front of it. The bearer check is real and
    the routes would still refuse a cookie -- but the reason this is safe today
    is that the surface is not reachable, and that is worth keeping as the
    reason rather than demoting it to defence in depth.
    """
    for name, prefixes in (
        ("docker/nginx.conf", _nginx_prefixes()),
        ("web/vite.config.js", _vite_prefixes()),
    ):
        offenders = [p for p in prefixes if p.startswith("/internal")]
        assert offenders == [], (
            f"{name} proxies {offenders} to the API: the internal control-plane "
            f"routes are for a sandbox on the internal network, not for the "
            f"portal's public origin"
        )
