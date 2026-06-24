"""S3-compatible storage client factory and file CRUD (boto3)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from config.settings import get_settings

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Client factory
# ──────────────────────────────────────────────

def get_s3_client():
    import boto3
    from botocore.config import Config

    cfg = get_settings().s3
    kwargs: dict = dict(
        service_name="s3",
        endpoint_url=cfg.endpoint,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        region_name=cfg.region,
        config=Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 1},
        ),
    )
    if cfg.insecure:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        kwargs["verify"] = False

    return boto3.client(**kwargs)


def ensure_bucket() -> None:
    from botocore.exceptions import ClientError

    cfg = get_settings().s3
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=cfg.rag_bucket)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=cfg.rag_bucket)
            logger.info("S3 bucket created: %s", cfg.rag_bucket)
        else:
            raise


# ──────────────────────────────────────────────
# Event dataclass
# ──────────────────────────────────────────────

@dataclass
class S3Event:
    event_type: str       # "PUT" | "DELETE"
    kb_id: str
    source: str       # "pdf/keycloak-guide.pdf" (without kb_id prefix)
    etag: str
    size: int
    cursor: str           # next polling cursor (event timestamp etc.)


# ──────────────────────────────────────────────
# Sensor event polling
# ──────────────────────────────────────────────

def poll_s3_events(cursor: str | None = None) -> list[S3Event]:
    """
    Poll the S3 bucket and return PUT events.

    Uses cursor (last-processed time as ISO string) to return only new objects.
    ClientError is logged and swallowed — polling must not crash the sensor loop.
    """
    import datetime

    from botocore.exceptions import ClientError

    cfg = get_settings().s3
    client = get_s3_client()
    events: list[S3Event] = []

    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=cfg.rag_bucket):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                parts = key.split("/", 1)
                if len(parts) < 2:
                    continue
                kb_id, source = parts[0], parts[1]

                last_modified = obj["LastModified"]
                if cursor and last_modified:
                    cursor_dt = datetime.datetime.fromisoformat(cursor)
                    if last_modified.replace(tzinfo=None) <= cursor_dt.replace(tzinfo=None):
                        continue

                events.append(
                    S3Event(
                        event_type="PUT",
                        kb_id=kb_id,
                        source=source,
                        etag=obj.get("ETag", "").strip('"'),
                        size=obj.get("Size", 0),
                        cursor=last_modified.isoformat(),
                    )
                )
    except ClientError as e:
        logger.error("S3 polling failed: %s", e)

    return events


# ──────────────────────────────────────────────
# File CRUD
# ──────────────────────────────────────────────

def download_object(kb_id: str, source: str, dest: Path) -> Path:
    """Download a file from S3 to a local path."""
    cfg = get_settings().s3
    client = get_s3_client()
    full_key = f"{kb_id}/{source}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(cfg.rag_bucket, full_key, str(dest))
    logger.info("S3 download done: %s -> %s", full_key, dest)
    return dest


def upload_object(
    kb_id: str,
    source: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    metadata: dict[str, str] | None = None,
) -> str:
    """Upload a file to S3 and return the ETag.

    metadata values are stored as x-amz-meta-* headers (boto3 adds the prefix automatically).
    """
    cfg = get_settings().s3
    client = get_s3_client()
    full_key = f"{kb_id}/{source}"

    kwargs: dict = dict(
        Bucket=cfg.rag_bucket,
        Key=full_key,
        Body=data,
        ContentType=content_type,
    )
    if metadata:
        kwargs["Metadata"] = metadata

    response = client.put_object(**kwargs)
    etag = response.get("ETag", "").strip('"')
    logger.info("S3 upload done: %s etag=%s", full_key, etag)
    return etag


def download_by_key(storage_key: str, dest: Path) -> Path:
    """Download a file from S3 using a full storage_key (e.g. 'kb-01/doc.pdf')."""
    cfg = get_settings().s3
    client = get_s3_client()
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(cfg.rag_bucket, storage_key, str(dest))
    logger.info("S3 download done: %s -> %s", storage_key, dest)
    return dest


def delete_object(kb_id: str, source: str) -> None:
    """Delete an object from S3."""
    cfg = get_settings().s3
    client = get_s3_client()
    full_key = f"{kb_id}/{source}"
    client.delete_object(Bucket=cfg.rag_bucket, Key=full_key)
    logger.info("S3 object deleted: %s", full_key)


def delete_by_key(storage_key: str) -> None:
    """Delete an object from S3 using a full storage_key."""
    cfg = get_settings().s3
    client = get_s3_client()
    client.delete_object(Bucket=cfg.rag_bucket, Key=storage_key)
    logger.info("S3 object deleted by key: %s", storage_key)


def delete_kb_prefix(kb_id: str) -> int:
    """Delete the entire KB prefix and return the number of objects deleted."""
    cfg = get_settings().s3
    client = get_s3_client()
    prefix = f"{kb_id}/"
    count = 0

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=cfg.rag_bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            client.delete_object(Bucket=cfg.rag_bucket, Key=obj["Key"])
            count += 1

    logger.info("S3 KB prefix deleted: %s count=%d", prefix, count)
    return count


def get_object_etag(kb_id: str, source: str) -> str | None:
    """Return the ETag for an object, or None if it doesn't exist."""
    etag, _ = get_object_meta(kb_id, source)
    return etag


def get_object_meta(kb_id: str, source: str) -> tuple[str | None, int]:
    """Return (etag, size) for an object using a single head_object call.

    Returns (None, 0) if the object does not exist or the call fails.
    """
    from botocore.exceptions import ClientError

    cfg = get_settings().s3
    client = get_s3_client()
    full_key = f"{kb_id}/{source}"
    try:
        response = client.head_object(Bucket=cfg.rag_bucket, Key=full_key)
        etag = response.get("ETag", "").strip('"') or None
        size = response.get("ContentLength", 0)
        return etag, size
    except ClientError:
        return None, 0


def get_object_last_modified(kb_id: str, source: str) -> str:
    """Return the LastModified timestamp for an object as an ISO 8601 UTC string.

    Returns empty string if the object does not exist or the call fails.
    """
    return get_object_last_modified_by_key(f"{kb_id}/{source}")


def get_object_last_modified_by_key(storage_key: str) -> str:
    """Return the LastModified timestamp for a storage_key as an ISO 8601 UTC string."""
    from botocore.exceptions import ClientError

    cfg = get_settings().s3
    client = get_s3_client()
    try:
        response = client.head_object(Bucket=cfg.rag_bucket, Key=storage_key)
        last_modified = response.get("LastModified")
        return last_modified.isoformat() if last_modified else ""
    except ClientError:
        return ""


def list_kb_objects(kb_id: str) -> list[tuple[str, str, str, int]]:
    """Return (source, etag, last_modified_iso, size) tuples for all objects under a KB prefix.

    last_modified_iso is an ISO 8601 UTC string (e.g. '2024-03-15T09:00:00+00:00').
    size is the object size in bytes (0 if unavailable).
    """
    from botocore.exceptions import ClientError

    cfg = get_settings().s3
    client = get_s3_client()
    prefix = f"{kb_id}/"
    results: list[tuple[str, str, str, int]] = []
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=cfg.rag_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"].removeprefix(prefix)
                if not key:
                    continue
                etag = obj.get("ETag", "").strip('"')
                last_modified = obj.get("LastModified")
                last_modified_iso = last_modified.isoformat() if last_modified else ""
                size = obj.get("Size", 0)
                results.append((key, etag, last_modified_iso, size))
    except ClientError as e:
        logger.error("S3 list_kb_objects failed: kb=%s err=%s", kb_id, e)
    return results
