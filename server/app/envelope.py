"""Envelope encryption for the secrets a tenant hands us (DESIGN.md §8).

A tenant's GitHub PAT is stored as ciphertext in Postgres and decrypted only in
the control plane at push time. Envelope encryption, rather than one long-lived
key encrypting every row: each secret gets its own random **data key**, that
data key is wrapped by a key that never leaves the KMS, and the wrapped form
travels beside the ciphertext. Two things follow, and both are the reason to
prefer it. Rotating the KMS key does not mean re-encrypting rows -- only
re-wrapping the small keys. And the secret itself never reaches the KMS, so a
PAT is never in a cloud provider's request log and no secret can outgrow the
KMS payload limit.

The sealed form is one self-describing string, so the column is text and the
format can gain a version without a migration:

    qa-env1$<wrapped data key>$<nonce>$<ciphertext+tag>    -- each base64url

AES-256-GCM, with the version prefix as additional authenticated data: a
ciphertext minted under a later format cannot be opened as if it were this one,
and any edit to any part of the string fails authentication rather than
decrypting to something.

**Two wrappers, one protocol.** `KmsKeyWrapper` is production. `LocalKeyWrapper`
is development and the test suite, which must run with no cloud account and no
network; it is real AES-GCM, so a round trip through it genuinely exercises the
format, but its wrapping key lives in the same process as the ciphertext it
protects -- which is exactly what a KMS exists to prevent. It is therefore
**not a production configuration**, and `wrapper_from_env` reports which of the
two it built so a deployment can say so out loud.
"""

from __future__ import annotations

import base64
import os
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# The format version, and the AAD every seal is bound to. Bumping it makes
# every older ciphertext fail authentication rather than be misread, which is
# the behaviour to want from a format change on a credential column.
SEAL_PREFIX = "qa-env1"

_DATA_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12     # the GCM standard, and what AESGCM expects


class SealError(Exception):
    """A sealed secret could not be opened: wrong key, wrong format, or edited.

    One exception for all three on purpose. "Which of these went wrong?" is a
    question an attacker asks more often than an operator, and the operator's
    answer is the same either way: this ciphertext is not usable, re-save the
    credential.
    """


class KeyWrapper(Protocol):
    """Wraps and unwraps a data key. The only thing that holds a long-lived key."""

    def wrap(self, data_key: bytes) -> bytes: ...
    def unwrap(self, wrapped: bytes) -> bytes: ...

    @property
    def describe(self) -> str:
        """What this wrapper is, for a startup log line. See `wrapper_from_env`."""
        ...


class LocalKeyWrapper:
    """A wrapper whose key is in this process. **Development and tests only.**

    It exists because the suite and `make up` must work with no cloud account:
    a format that can only be exercised against real KMS is a format nothing
    tests. The wrapping key is derived with HKDF rather than used raw, so a
    short or low-entropy `QA_SECRET_KEY` still yields a 32-byte AES key, and so
    the same secret used for cookie signing does not become the literal
    encryption key.
    """

    def __init__(self, secret: bytes | str) -> None:
        material = secret.encode() if isinstance(secret, str) else secret
        self._key = HKDF(
            algorithm=hashes.SHA256(),
            length=_DATA_KEY_BYTES,
            salt=None,
            info=b"qa-portal/envelope/local-key-wrapper",
        ).derive(material)

    @property
    def describe(self) -> str:
        return "local (in-process key; not a production configuration)"

    def wrap(self, data_key: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + AESGCM(self._key).encrypt(nonce, data_key, SEAL_PREFIX.encode())

    def unwrap(self, wrapped: bytes) -> bytes:
        nonce, body = wrapped[:_NONCE_BYTES], wrapped[_NONCE_BYTES:]
        try:
            return AESGCM(self._key).decrypt(nonce, body, SEAL_PREFIX.encode())
        except (InvalidTag, ValueError) as exc:
            raise SealError("the data key could not be unwrapped") from exc


class KmsKeyWrapper:
    """Production: the wrapping key lives in a cloud KMS and never leaves it.

    `kms.encrypt`/`kms.decrypt` are called on the **data key only** -- 32 bytes,
    never the secret -- so a PAT is never in a KMS request and therefore never
    in the provider's own audit log of those requests. That is the property the
    envelope buys over calling `kms.encrypt` on the PAT directly, which would
    otherwise have been the shorter code.

    The client is injectable for the same reason `Storage`'s and
    `GitHubClient`'s are: a wrapper nothing can substitute is a wrapper nothing
    tests offline.
    """

    def __init__(self, key_id: str, *, client=None) -> None:
        self._key_id = key_id
        self._client = client if client is not None else kms_client()

    @property
    def describe(self) -> str:
        return f"cloud KMS (key {self._key_id})"

    def wrap(self, data_key: bytes) -> bytes:
        try:
            return self._client.encrypt(KeyId=self._key_id, Plaintext=data_key)[
                "CiphertextBlob"
            ]
        except Exception as exc:  # boto3 raises a family; the caller needs one
            raise SealError(f"the KMS could not wrap a data key: {exc}") from exc

    def unwrap(self, wrapped: bytes) -> bytes:
        try:
            return self._client.decrypt(CiphertextBlob=wrapped)["Plaintext"]
        except Exception as exc:
            raise SealError(f"the KMS could not unwrap a data key: {exc}") from exc


def kms_client():
    """A boto3 KMS client, built from the ambient AWS configuration.

    Its own function so tests substitute it without a network call and without
    needing AWS credentials to exist -- the sibling of `storage.from_env`.
    """
    import boto3

    return boto3.client("kms", region_name=os.environ.get("AWS_REGION") or None)


def wrapper_from_env() -> KeyWrapper:
    """The wrapper this deployment is configured for.

    `QA_KMS_KEY_ID` is what makes it production. Without it the local wrapper is
    built so the suite and the dev stack work offline -- and `describe` says
    which one was built, so a deployment that forgot the variable can be seen
    to have forgotten it rather than silently storing PATs under a key sitting
    in its own process.
    """
    key_id = os.environ.get("QA_KMS_KEY_ID", "").strip()
    if key_id:
        return KmsKeyWrapper(key_id)
    return LocalKeyWrapper(os.environ.get("QA_SECRET_KEY", "dev-secret-change-me"))



# --- the sealed form ------------------------------------------------------

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (ValueError, TypeError) as exc:
        raise SealError("the sealed secret is not valid base64") from exc


def seal(plaintext: str, wrapper: KeyWrapper) -> str:
    """Encrypt `plaintext` under a fresh data key, wrapped by `wrapper`."""
    data_key = os.urandom(_DATA_KEY_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    body = AESGCM(data_key).encrypt(nonce, plaintext.encode(), SEAL_PREFIX.encode())
    return "$".join((SEAL_PREFIX, _b64(wrapper.wrap(data_key)), _b64(nonce), _b64(body)))


def open_sealed(sealed: str, wrapper: KeyWrapper) -> str:
    """The plaintext a sealed string holds, or `SealError`."""
    parts = sealed.split("$")
    if len(parts) != 4 or parts[0] != SEAL_PREFIX:
        raise SealError(f"not a {SEAL_PREFIX} sealed secret")
    _, wrapped, nonce, body = parts
    data_key = wrapper.unwrap(_unb64(wrapped))
    try:
        return AESGCM(data_key).decrypt(
            _unb64(nonce), _unb64(body), SEAL_PREFIX.encode()
        ).decode()
    except (InvalidTag, ValueError) as exc:
        raise SealError("the sealed secret could not be opened") from exc
