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
    object_key: str       # "pdf/keycloak-guide.pdf" (without kb_id prefix)
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
                kb_id, object_key = parts[0], parts[1]

                last_modified = obj["LastModified"]
                if cursor and last_modified:
                    cursor_dt = datetime.datetime.fromisoformat(cursor)
                    if last_modified.replace(tzinfo=None) <= cursor_dt.replace(tzinfo=None):
                        continue

                events.append(
                    S3Event(
                        event_type="PUT",
                        kb_id=kb_id,
                        object_key=object_key,
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

def download_object(kb_id: str, object_key: str, dest: Path) -> Path:
    """Download a file from S3 to a local path."""
    cfg = get_settings().s3
    client = get_s3_client()
    full_key = f"{kb_id}/{object_key}"

    dest.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(cfg.rag_bucket, full_key, str(dest))
    logger.info("S3 download done: %s -> %s", full_key, dest)
    return dest


def upload_object(kb_id: str, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload a file to S3 and return the ETag."""
    cfg = get_settings().s3
    client = get_s3_client()
    full_key = f"{kb_id}/{object_key}"

    response = client.put_object(
        Bucket=cfg.rag_bucket,
        Key=full_key,
        Body=data,
        ContentType=content_type,
    )
    etag = response.get("ETag", "").strip('"')
    logger.info("S3 upload done: %s etag=%s", full_key, etag)
    return etag


def delete_object(kb_id: str, object_key: str) -> None:
    """Delete an object from S3."""
    cfg = get_settings().s3
    client = get_s3_client()
    full_key = f"{kb_id}/{object_key}"
    client.delete_object(Bucket=cfg.rag_bucket, Key=full_key)
    logger.info("S3 object deleted: %s", full_key)


def delete_kb_prefix(kb_id: str) -> int:
    """Delete the entire KB prefix and return the number of objects deleted."""
    cfg = get_settings().s3
    client = get_s3_client()
    prefix = f"{kb_id}/"
    count = 0

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=cfg.rag_bucket, Prefix=prefix):
        objects = page.get("Contents", [])
        if objects:
            delete_keys = [{"Key": obj["Key"]} for obj in objects]
            client.delete_objects(
                Bucket=cfg.rag_bucket,
                Delete={"Objects": delete_keys},
            )
            count += len(delete_keys)

    logger.info("S3 KB prefix deleted: %s count=%d", prefix, count)
    return count


def get_object_etag(kb_id: str, object_key: str) -> str | None:
    """Return the ETag for an object, or None if it doesn't exist."""
    from botocore.exceptions import ClientError

    cfg = get_settings().s3
    client = get_s3_client()
    full_key = f"{kb_id}/{object_key}"
    try:
        response = client.head_object(Bucket=cfg.rag_bucket, Key=full_key)
        return response.get("ETag", "").strip('"')
    except ClientError:
        return None


def list_kb_objects(kb_id: str) -> list[tuple[str, str]]:
    """Return (object_key, etag) pairs for all objects under a KB prefix."""
    from botocore.exceptions import ClientError

    cfg = get_settings().s3
    client = get_s3_client()
    prefix = f"{kb_id}/"
    results: list[tuple[str, str]] = []
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=cfg.rag_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"].removeprefix(prefix)
                if not key:
                    continue
                etag = obj.get("ETag", "").strip('"')
                results.append((key, etag))
    except ClientError as e:
        logger.error("S3 list_kb_objects failed: kb=%s err=%s", kb_id, e)
    return results
