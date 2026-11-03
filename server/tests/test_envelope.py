"""Envelope encryption: the sealed form, and what it does not carry.

The one test that matters most here is not the round trip -- it is that the
sealed string holds neither the secret nor the key that would open it, because
that is the whole claim a database dump has to survive (DESIGN.md §8).
"""

from __future__ import annotations

import pytest

from app import envelope

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
    monkeypatch.delenv("QA_KMS_KEY_ID", raising=False)
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
