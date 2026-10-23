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

    def get_stream(self, key: str) -> tuple[Iterator[bytes], str]:
        obj = self._client.get_object(Bucket=self.bucket, Key=key)
        ct = obj.get("ContentType") or content_type_for(key)
        return obj["Body"].iter_chunks(chunk_size=64 * 1024), ct


def from_env() -> S3Storage:
    return S3Storage(
        endpoint=os.environ.get("S3_ENDPOINT", "http://localhost:8333"),
        access_key=os.environ.get("S3_ACCESS_KEY", "qa"),
        secret_key=os.environ.get("S3_SECRET_KEY", "qa-secret"),
        bucket=os.environ.get("S3_BUCKET", "qa-artifacts"),
    )
