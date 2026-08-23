"""Bronze-tier object storage (report 4.3): exact bytes as fetched, immutable,
provenance-tagged. Two implementations behind one protocol so tests run
without any infra and production runs against MinIO/S3 with no code change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config as BotoConfig

from wardline.common.config import get_settings


class BlobStore(Protocol):
    def put(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> str: ...
    def get(self, key: str) -> bytes: ...
    def put_json_sidecar(self, key: str, obj: dict) -> None: ...


class LocalFSBlobStore:
    """Filesystem-backed store — used in tests and as a zero-infra fallback."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or get_settings().blob_local_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> str:
        self._path(key).write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def put_json_sidecar(self, key: str, obj: dict) -> None:
        self._path(f"{key}.provenance.json").write_text(json.dumps(obj, default=str))


class S3BlobStore:
    """S3-API store — points at MinIO by default (docker-compose), or real AWS
    S3 in a true production deployment with no code change, just env vars."""

    def __init__(self):
        settings = get_settings()
        self._bucket = settings.s3_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            config=BotoConfig(signature_version="s3v4"),
        )

    def put(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, Metadata=metadata or {})
        return key

    def get(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"].read()

    def put_json_sidecar(self, key: str, obj: dict) -> None:
        self._client.put_object(
            Bucket=self._bucket,
            Key=f"{key}.provenance.json",
            Body=json.dumps(obj, default=str).encode("utf-8"),
        )


def get_blob_store() -> BlobStore:
    settings = get_settings()
    if settings.blob_backend == "s3":
        return S3BlobStore()
    return LocalFSBlobStore()
