"""The internal control plane: what a run may ask of Postgres and the stores.

Before P5-05 a sandbox held `DATABASE_URL` and the `S3_*` credentials and did
its own reads and writes. This package is what replaced them:

    app/run_token.py        the bearer token: one run, one target, one tenant
    control/model.py        the values that cross the boundary
    control/service.py      every operation, and the one place each is authorized
    control/gateway.py      the protocol the run-side code calls
    control/local.py        the gateway that calls the service in this process
    control/http.py         the gateway that calls it over the internal API
    app/internal_api.py     the routes, which are thin wrappers over the service

**One set of operations, two transports.** The thread path (`QA_SANDBOX=thread`,
which is CI and development) uses `LocalGateway`; the container path uses
`HttpGateway`. They are two ways of reaching `service.py`, not two
implementations of it, so there is no second behaviour for the suite to miss --
the thing P4 established about the pipeline (`drive_run` is one function with two
call sites) applied to the control plane the pipeline talks to.

Both paths mint and present a real token, so the scope and liveness checks are
exercised whichever one runs. What only the HTTP path exercises is the framing:
JSON, status codes and streaming. That is what tests/test_internal_api.py is for,
and tests/test_control_gateway.py runs one suite against both gateways so the two
cannot drift.
"""
