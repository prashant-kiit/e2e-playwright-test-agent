"""Whether this process believes it is a development stack or a deployment.

The portal had no such signal until the two credential fixes needed one: the
session cookies' `Secure` flag has to be off for plain-HTTP development and on
everywhere else, and the envelope's local key fallback has to exist for
development and be refused everywhere else. Both are the same question, so
both read the same variable rather than growing a knob each.

**The default is `prod`**, which is the whole point of the design. A deployment
that forgets `QA_ENV` gets `Secure` cookies and a refusal to boot without an
envelope key; the insecure arrangement is the one you have to ask for by name.
That direction is the lesson of `VERIFICATION-P5.md` follow-up 21 -- a fallback
nothing warned about -- applied to its own fix.
"""

from __future__ import annotations

import pytest

from app import config


def test_the_default_is_production(monkeypatch):
    """Unset is not development. See the module docstring: this is the fix."""
    monkeypatch.delenv("QA_ENV", raising=False)

    assert config.is_dev_deployment() is False
    assert config.cookies_secure() is True


def test_dev_is_opt_in_by_name(monkeypatch):
    monkeypatch.setenv("QA_ENV", "dev")

    assert config.is_dev_deployment() is True
    assert config.cookies_secure() is False


@pytest.mark.parametrize("value", ["DEV", "Dev", " dev "])
def test_the_value_is_read_case_and_space_insensitively(monkeypatch, value):
    """`QA_ENV=DEV` in a compose file is a development stack. Matching the
    tolerance `config.runner_kind` and `config.sandbox_kind` already have."""
    monkeypatch.setenv("QA_ENV", value)

    assert config.is_dev_deployment() is True


@pytest.mark.parametrize("value", ["prod", "production", "staging", "", "nonsense"])
def test_anything_that_is_not_dev_is_a_deployment(monkeypatch, value):
    """Including a typo and the empty string. A misspelled `QA_ENV=devv` must
    not be the insecure branch -- the failure mode of guessing wrong here is a
    30-day refresh credential travelling over plain HTTP, so only the exact
    word opts out."""
    monkeypatch.setenv("QA_ENV", value)

    assert config.is_dev_deployment() is False


# --- the startup check ----------------------------------------------------


def test_a_misconfigured_deployment_does_not_start(monkeypatch):
    """The refusal has to happen at boot to be worth having.

    `wrapper_from_env` is called lazily, at the moment a credential is saved or
    a delivery decrypts one. A deployment that reached production with neither
    key configured would therefore start, serve, and refuse the first customer
    who pasted a PAT -- an operator reading a 500 from one route rather than a
    process that would not come up. So the lifespan builds the wrapper once.
    """
    from fastapi.testclient import TestClient

    from app.envelope import CredentialConfigError
    from app.main import app

    monkeypatch.setenv("QA_REAPER", "0")
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.delenv("QA_ENVELOPE_KEY", raising=False)
    monkeypatch.delenv("QA_ENV", raising=False)  # i.e. a deployment

    with pytest.raises(CredentialConfigError):
        with TestClient(app):
            pass


def test_a_configured_deployment_starts_and_reports_its_wrapper(monkeypatch, caplog):
    """And the other side: it starts, and it says out loud which wrapper it
    built. `describe` was written for a startup log line and nothing had ever
    called it, so a deployment silently running the in-process key looked
    exactly like one running a KMS.
    """
    import logging

    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("QA_REAPER", "0")
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("QA_ENVELOPE_KEY", "a-configured-key")
    monkeypatch.delenv("QA_ENV", raising=False)

    with caplog.at_level(logging.INFO, logger="app.main"):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200

    assert "not a production configuration" in caplog.text


def test_a_deployment_on_the_in_process_key_warns_rather_than_informs(
    monkeypatch, caplog
):
    """At `WARNING`, because at `INFO` nobody would ever read it.

    The API process installs no logging configuration -- uvicorn configures
    its own loggers and leaves everything else to the root logger, which has
    no handler -- so an `app.*` record below `WARNING` is dropped before it
    reaches a terminal. Checked against a real `uvicorn` boot, not inferred:
    the first version of this logged the line at `INFO` and printed nothing at
    all, which would have made "a deployment running the in-process key can be
    seen to be running it" false in exactly the deployment it is about.

    The level is also the honest one. A deployment with no KMS is storing every
    customer's PAT under a key in its own process, which `envelope.py` calls
    "not a production configuration" -- that is a warning, not news.
    """
    import logging

    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("QA_ENVELOPE_KEY", "a-configured-key")
    monkeypatch.delenv("QA_ENV", raising=False)

    with caplog.at_level(logging.INFO, logger="app.main"):
        from app.main import check_credential_config

        check_credential_config()

    assert [r.levelno for r in caplog.records] == [logging.WARNING]
    assert "not a production configuration" in caplog.text


def test_a_development_stack_does_not_warn_about_its_own_key(monkeypatch, caplog):
    """A dev stack is *supposed* to be on the in-process key, so warning about
    it on every `make up` would be a warning people learn to ignore -- and the
    one above has to still mean something when it appears."""
    import logging

    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.delenv("QA_ENVELOPE_KEY", raising=False)
    monkeypatch.setenv("QA_ENV", "dev")

    with caplog.at_level(logging.INFO, logger="app.main"):
        from app.main import check_credential_config

        check_credential_config()

    assert [r.levelno for r in caplog.records] == [logging.INFO]
