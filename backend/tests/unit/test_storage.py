"""Storage backends. S3 uses botocore's Stubber (a test double); no real bucket is contacted."""

from __future__ import annotations

import io
from pathlib import Path

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from app.core.config import Settings, StorageBackend
from app.core.storage import LocalStorage, S3Storage

KEY = "avatar/" + "a" * 32


async def test_local_storage_roundtrip(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path))
    await storage.put(KEY, b"hello", "image/png")
    assert await storage.get(KEY) == b"hello"
    await storage.delete(KEY)
    with pytest.raises(FileNotFoundError):
        await storage.get(KEY)


@pytest.mark.parametrize("key", ["../etc/passwd", "avatar/../../x", "AVATAR/abc", "avatar/" + "g" * 32])
async def test_storage_rejects_unexpected_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError, match="Invalid storage key"):
        await LocalStorage(str(tmp_path)).put(key, b"x", "image/png")


async def test_s3_storage_uses_bucket_and_content_type() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+psycopg://u:p@localhost/db",
        jwt_secret="s" * 40,
        storage_backend=StorageBackend.S3,
        s3_bucket="unifix-test-bucket",
    )
    client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="y")
    stubber = Stubber(client)
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "unifix-test-bucket", "Key": KEY, "Body": b"data", "ContentType": "image/png"},
    )
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"data"), 4)},
        {"Bucket": "unifix-test-bucket", "Key": KEY},
    )
    stubber.add_response("delete_object", {}, {"Bucket": "unifix-test-bucket", "Key": KEY})
    with stubber:
        storage = S3Storage(settings, client=client)
        await storage.put(KEY, b"data", "image/png")
        assert await storage.get(KEY) == b"data"
        await storage.delete(KEY)
    stubber.assert_no_pending_responses()
