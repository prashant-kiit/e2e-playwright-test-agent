"""Artifact blob storage: an S3 interface, backed by SeaweedFS in the dev stack.

Storage is a protocol so the collector and API can be tested with an in-memory
fake (no S3). S3Storage talks to any S3-compatible endpoint; SeaweedFS is the
one we ship (MinIO was dropped — see the plan). Blobs live here; the Postgres
`artifacts` table indexes them.
"""

from __future__ import annotations

import mimetypes
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol


def content_type_for(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


class Storage(Protocol):
    def ensure_bucket(self) -> None: ...
    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None: ...
    def get_stream(self, key: str) -> tuple[Iterator[bytes], str]: ...
    def exists(self, key: str) -> bool: ...
    # Added by P5-08 (#40) as a prefactor for tenant purge, which has to remove
    # objects nobody recorded individually. Nothing called either when they
    # landed; `accounts.purge` and `artifacts.rekey` do now. Their semantics --
    # a delete that tolerates a missing key, a listing that pages -- are held
    # by tests/test_storage_guard.py.
    def delete(self, key: str) -> None: ...
    def list_keys(self, prefix: str) -> Iterator[str]: ...


class S3Storage:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self.bucket)

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        self.ensure_bucket()
        with path.open("rb") as fh:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=fh,
                ContentType=content_type or content_type_for(key),
            )

    def exists(self, key: str) -> bool:
        """Whether an object is already stored under `key`.

        Content addressing makes this the dedup check: a blob key *is* its
        content hash, so an object that exists holds exactly the bytes about to
        be uploaded. A missing bucket is simply "no".
        """
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True

    def get_stream(self, key: str) -> tuple[Iterator[bytes], str]:
        obj = self._client.get_object(Bucket=self.bucket, Key=key)
        ct = obj.get("ContentType") or content_type_for(key)
        return obj["Body"].iter_chunks(chunk_size=64 * 1024), ct

    def delete(self, key: str) -> None:
        """Remove one object. **A key that is not there is not an error.**

        S3 `DeleteObject` is already idempotent, so this is the semantics of
        the API rather than something handled here -- and it is the semantics
        tenant purge needs, because a purge has to be re-runnable after a
        partial failure. A missing bucket is the same story: there is nothing
        under the key either way.
        """
        from botocore.exceptions import ClientError

        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError:
            # NoSuchBucket, and nothing else that matters: an object that is
            # not there is already the state the caller asked for.
            pass

    def list_keys(self, prefix: str) -> Iterator[str]:
        """Every key under `prefix`, **paging through the whole result set**.

        A paginator rather than one `list_objects_v2`, because that call
        returns at most 1000 keys and silently truncates: a tenant with a long
        run history would be purged down to its first thousand objects and
        reported as done. This is the one part of the operation that can be
        wrong while looking right, which is why it is a paginator and why a
        test drives it with more than one page.

        A generator, so a purge streams rather than holding a tenant's whole
        key space in memory. An empty or missing prefix yields nothing rather
        than raising -- a tenant with no objects is an ordinary case.
        """
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", ()):
                yield obj["Key"]


def from_env() -> S3Storage:
    return S3Storage(
        endpoint=os.environ.get("S3_ENDPOINT", "http://localhost:8333"),
        access_key=os.environ.get("S3_ACCESS_KEY", "qa"),
        secret_key=os.environ.get("S3_SECRET_KEY", "qa-secret"),
        bucket=os.environ.get("S3_BUCKET", "qa-artifacts"),
    )
