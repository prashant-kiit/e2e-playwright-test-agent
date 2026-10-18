"""FastAPI entrypoint for the QA admin portal backend.

This is the M0 scaffold: a single health endpoint. Later milestones add the
state store, orchestrator, artifacts and the rest of the API on top of this app.
"""

from fastapi import FastAPI

app = FastAPI(title="QA Portal", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by docker-compose and the portal."""
    return {"status": "ok", "service": "qa-portal"}
