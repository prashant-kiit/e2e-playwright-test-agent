"""Envelope encryption: the sealed form, and what it does not carry.

The one test that matters most here is not the round trip -- it is that the
sealed string holds neither the secret nor the key that would open it, because
that is the whole claim a database dump has to survive (DESIGN.md §8).
"""

from __future__ import annotations

import pytest

from app import config, envelope

PAT = "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


@pytest.fixture()
def wrapper():
    return envelope.LocalKeyWrapper(b"a-wrapping-key-for-the-suite")


def test_a_sealed_secret_opens_again(wrapper):
    assert envelope.open_sealed(envelope.seal(PAT, wrapper), wrapper) == PAT


def test_the_sealed_form_carries_neither_the_secret_nor_a_usable_key(wrapper):
    """What a stolen database dump holds: the ciphertext, and a data key that is
    itself encrypted under a key the dump does not contain."""
    sealed = envelope.seal(PAT, wrapper)

    assert PAT not in sealed
    assert "ghp_" not in sealed
    with pytest.raises(envelope.SealError):
        envelope.open_sealed(sealed, envelope.LocalKeyWrapper(b"a-different-key"))


def test_sealing_the_same_secret_twice_gives_different_bytes(wrapper):
    """A fresh data key and nonce per seal, so equal ciphertexts never reveal
    that two tenants pasted the same token."""
    assert envelope.seal(PAT, wrapper) != envelope.seal(PAT, wrapper)


def test_an_edited_ciphertext_is_refused_rather_than_decrypted(wrapper):
    """AES-GCM authenticates, so a flipped byte is a refusal and never a token
    that is subtly not the one the tenant saved."""
    sealed = envelope.seal(PAT, wrapper)
    prefix, wrapped, nonce, body = sealed.split("$")
    edited = "$".join((prefix, wrapped, nonce, body[:-4] + "AAAA"))

    with pytest.raises(envelope.SealError):
        envelope.open_sealed(edited, wrapper)


def test_a_sealed_secret_from_another_format_version_is_refused(wrapper):
    """The version prefix is the AAD, so it cannot be relabelled either."""
    sealed = envelope.seal(PAT, wrapper)

    with pytest.raises(envelope.SealError, match="qa-env1"):
        envelope.open_sealed("qa-env2" + sealed[len("qa-env1"):], wrapper)


def test_something_that_is_not_a_sealed_secret_is_refused(wrapper):
    for text in ("", "ghp_a_bare_token", "qa-env1$only$three"):
        with pytest.raises(envelope.SealError):
            envelope.open_sealed(text, wrapper)


# --- the KMS wrapper: the data key goes out, the secret never does -------

class StubKms:
    """Only the two KMS calls the wrapper makes, with what it was asked recorded."""

    def __init__(self) -> None:
        self.encrypted: list[bytes] = []
        self.key_ids: list[str] = []

    def encrypt(self, *, KeyId: str, Plaintext: bytes) -> dict:  # noqa: N803 (boto3 spelling)
        self.encrypted.append(Plaintext)
        self.key_ids.append(KeyId)
        return {"CiphertextBlob": b"wrapped:" + Plaintext}

    def decrypt(self, *, CiphertextBlob: bytes) -> dict:  # noqa: N803
        assert CiphertextBlob.startswith(b"wrapped:")
        return {"Plaintext": CiphertextBlob[len(b"wrapped:"):]}


def test_the_kms_wrapper_sends_only_the_data_key_to_the_kms():
    """The envelope's whole point: the PAT is never in a KMS request, so it is
    never in a cloud provider's audit log."""
    kms = StubKms()
    wrapper = envelope.KmsKeyWrapper("arn:aws:kms:eu-west-1:1:key/abc", client=kms)

    sealed = envelope.seal(PAT, wrapper)

    assert envelope.open_sealed(sealed, wrapper) == PAT
    assert kms.key_ids == ["arn:aws:kms:eu-west-1:1:key/abc"]
    assert len(kms.encrypted) == 1
    assert len(kms.encrypted[0]) == 32, "a 256-bit data key, not the secret"
    assert PAT.encode() not in kms.encrypted[0]


def test_a_kms_failure_is_a_seal_error_rather_than_a_boto_exception():
    """So a credential route answers "could not store this" instead of 500."""

    class Broken:
        def encrypt(self, **kwargs):
            raise RuntimeError("kms is unreachable")

        def decrypt(self, **kwargs):
            raise RuntimeError("kms is unreachable")

    wrapper = envelope.KmsKeyWrapper("k", client=Broken())
    with pytest.raises(envelope.SealError):
        envelope.seal(PAT, wrapper)


# --- which wrapper a deployment gets ------------------------------------

def test_without_a_kms_key_the_local_wrapper_is_built_and_says_so(monkeypatch):
    """`QA_SECRET_KEY` is set here and must make no difference: this module
    does not read it any more (follow-up 21, below)."""
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("QA_ENV", "dev")
    monkeypatch.setenv("QA_SECRET_KEY", "dev-secret")

    built = envelope.wrapper_from_env()

    assert isinstance(built, envelope.LocalKeyWrapper)
    assert "not a production configuration" in built.describe


def test_with_a_kms_key_the_kms_wrapper_is_built(monkeypatch):
    monkeypatch.setenv("QA_KMS_KEY_ID", "arn:aws:kms:eu-west-1:1:key/abc")
    monkeypatch.setattr(envelope, "kms_client", lambda: StubKms())

    built = envelope.wrapper_from_env()

    assert isinstance(built, envelope.KmsKeyWrapper)
    assert "arn:aws:kms:eu-west-1:1:key/abc" in built.describe


def test_a_kms_failure_does_not_echo_the_data_key():
    """botocore reports a bad parameter by echoing its value, and the parameter
    here is `Plaintext=<the data key>` -- the one thing that opens the seal. The
    wrapper's own error must name what failed without quoting what it was given.
    """
    data_keys: list[bytes] = []

    class EchoingKms:
        def encrypt(self, *, KeyId: str, Plaintext: bytes) -> dict:  # noqa: N803
            data_keys.append(Plaintext)
            raise ValueError(
                f"Parameter validation failed: Invalid type for Plaintext={Plaintext!r}"
            )

        def decrypt(self, *, CiphertextBlob: bytes) -> dict:  # noqa: N803
            raise AssertionError("not reached")

    wrapper = envelope.KmsKeyWrapper("alias/qa", client=EchoingKms())

    with pytest.raises(envelope.SealError) as caught:
        envelope.seal(PAT, wrapper)

    assert data_keys, "the wrapper never called the KMS, so this proves nothing"
    message = str(caught.value)
    for fragment in (repr(data_keys[0]), str(data_keys[0])):
        assert fragment not in message
    # Still diagnosable: it says the wrap failed and what kind of failure it was.
    assert "wrap" in message
    assert "ValueError" in message


# --- the key the local wrapper derives from ------------------------------
#
# `VERIFICATION-P5.md` follow-up 21: wherever `QA_KMS_KEY_ID` is unset -- every
# deployment at the time it was written -- `QA_SECRET_KEY` was both the cookie
# signing secret and the key protecting every stored customer PAT. One
# variable, two unrelated jobs, one of which is "read every customer's GitHub
# credential". The envelope was already real; the key was in the wrong place.
#
# `QA_ENVELOPE_KEY` is now that key, and this module no longer reads
# `QA_SECRET_KEY` at all.


def test_rotating_the_cookie_secret_no_longer_destroys_a_stored_pat(monkeypatch):
    """The fix, stated as the behaviour that was broken.

    Follow-up 21's complaint was that rotating `QA_SECRET_KEY` -- a thing an
    operator does for an unrelated reason, like a leaked session-forging key --
    silently made every stored PAT undecryptable. A seal taken before the
    rotation must open after it.
    """
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("QA_ENVELOPE_KEY", "the-envelope-key")

    monkeypatch.setenv("QA_SECRET_KEY", "cookie-secret-before")
    sealed = envelope.seal(PAT, envelope.wrapper_from_env())

    monkeypatch.setenv("QA_SECRET_KEY", "cookie-secret-after-the-rotation")

    assert envelope.open_sealed(sealed, envelope.wrapper_from_env()) == PAT


def test_the_cookie_secret_is_not_the_envelope_key_even_in_development(
    monkeypatch,
):
    """And the dev fallback is a constant of its own, not `QA_SECRET_KEY`.

    This is what actually severs the two jobs. A dev fallback that read
    `QA_SECRET_KEY` would leave the dev stack in exactly the arrangement
    follow-up 21 describes, and the fix real only where somebody had set the
    new variable.
    """
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.delenv("QA_ENVELOPE_KEY", raising=False)
    monkeypatch.setenv("QA_ENV", "dev")

    monkeypatch.setenv("QA_SECRET_KEY", "one-secret")
    sealed = envelope.seal(PAT, envelope.wrapper_from_env())
    monkeypatch.setenv("QA_SECRET_KEY", "a-completely-different-secret")

    assert envelope.open_sealed(sealed, envelope.wrapper_from_env()) == PAT


def test_a_deployment_with_no_envelope_key_is_refused(monkeypatch):
    """The startup check. Without this the fix would be decorative: a
    deployment that set neither variable would quietly fall back to the
    well-known development constant, which is strictly worse than the
    arrangement being fixed -- `QA_SECRET_KEY` was at least secret.
    """
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.delenv("QA_ENVELOPE_KEY", raising=False)
    monkeypatch.delenv("QA_ENV", raising=False)  # i.e. a deployment

    with pytest.raises(envelope.CredentialConfigError) as excinfo:
        envelope.wrapper_from_env()

    assert "QA_ENVELOPE_KEY" in str(excinfo.value)
    assert "QA_KMS_KEY_ID" in str(excinfo.value)


def test_the_two_keys_may_not_be_the_same_value(monkeypatch):
    """Setting both variables to the same string is follow-up 21 spelled by
    hand, and it is the likeliest way to "fix" this by copying a line in a
    deployment config. Refused in development too: it is never what anyone
    means, and the one place it would be discovered otherwise is an incident.
    """
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("QA_ENV", "dev")
    monkeypatch.setenv("QA_SECRET_KEY", "the-same-string")
    monkeypatch.setenv("QA_ENVELOPE_KEY", "the-same-string")

    with pytest.raises(envelope.CredentialConfigError) as excinfo:
        envelope.wrapper_from_env()

    assert "must not be the same" in str(excinfo.value)


def test_a_kms_key_makes_the_envelope_key_irrelevant(monkeypatch):
    """`QA_KMS_KEY_ID` is still what makes this production, and a deployment
    that has one needs no local key at all -- the refusal above must not fire
    for the configuration it is trying to push people towards."""
    monkeypatch.setenv("QA_KMS_KEY_ID", "arn:aws:kms:eu-west-1:1:key/abc")
    monkeypatch.delenv("QA_ENVELOPE_KEY", raising=False)
    monkeypatch.delenv("QA_ENV", raising=False)
    monkeypatch.setattr(envelope, "kms_client", lambda: StubKms())

    assert isinstance(envelope.wrapper_from_env(), envelope.KmsKeyWrapper)


def test_a_deployment_with_an_envelope_key_but_no_kms_still_says_it_is_not_production(
    monkeypatch,
):
    """Allowed, because the local wrapper's existence is a recorded decision
    (§Decisions) and refusing it would make `QA_KMS_KEY_ID` mandatory -- a
    bigger change than this fix. But `describe` must keep saying what it is, so
    the startup log of such a deployment reads as the compromise it is.
    """
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.delenv("QA_ENV", raising=False)
    monkeypatch.setenv("QA_ENVELOPE_KEY", "a-real-but-local-key")

    built = envelope.wrapper_from_env()

    assert isinstance(built, envelope.LocalKeyWrapper)
    assert "not a production configuration" in built.describe


def test_the_envelope_key_may_not_be_the_cookie_secrets_development_default(
    monkeypatch,
):
    """The same-value refusal, in the configuration that actually bypassed it.

    Found by review. `QA_SECRET_KEY` has a development fallback --
    `config.DEV_SECRET_KEY` -- which really does sign cookies, so with the
    variable unset and `QA_ENVELOPE_KEY` set to that same string, the two keys
    *are* identical. The first version of this guard compared `QA_ENVELOPE_KEY`
    against `os.environ.get("QA_SECRET_KEY", "")` and so compared it to the
    empty string and allowed it: follow-up 21 reintroduced, in the one
    configuration three documents call refused.

    The comparison is therefore against the key that is **in effect**, which
    `config` is the single place to resolve.
    """
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.delenv("QA_SECRET_KEY", raising=False)
    monkeypatch.setenv("QA_ENV", "dev")
    monkeypatch.setenv("QA_ENVELOPE_KEY", config.DEV_SECRET_KEY)

    with pytest.raises(envelope.CredentialConfigError) as excinfo:
        envelope.wrapper_from_env()

    assert "QA_SECRET_KEY" in str(excinfo.value)


def test_the_envelope_key_may_not_be_the_run_token_key_either(monkeypatch):
    """`QA_RUN_TOKEN_KEY` signs the token that is a sandbox's whole authority,
    so sharing it with the PAT-decrypting key is the same smell as sharing the
    cookie key -- and it was unrefused while only `QA_SECRET_KEY` was checked.
    """
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("QA_ENV", "dev")
    monkeypatch.setenv("QA_SECRET_KEY", "the-cookie-key")
    monkeypatch.setenv("QA_RUN_TOKEN_KEY", "the-run-token-key")
    monkeypatch.setenv("QA_ENVELOPE_KEY", "the-run-token-key")

    with pytest.raises(envelope.CredentialConfigError) as excinfo:
        envelope.wrapper_from_env()

    assert "QA_RUN_TOKEN_KEY" in str(excinfo.value)


def test_the_three_keys_all_differing_is_the_configuration_that_works(monkeypatch):
    """The other side of both refusals, so they cannot pass by refusing
    everything."""
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
    monkeypatch.setenv("QA_ENV", "dev")
    monkeypatch.setenv("QA_SECRET_KEY", "cookie")
    monkeypatch.setenv("QA_RUN_TOKEN_KEY", "run-tokens")
    monkeypatch.setenv("QA_ENVELOPE_KEY", "envelope")

    assert isinstance(envelope.wrapper_from_env(), envelope.LocalKeyWrapper)
