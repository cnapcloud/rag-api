"""One-shot migration: copy KB and document metadata from Redis to Postgres.

Run once with the service stopped:
    PYTHONPATH=src python scripts/migrate_redis_to_postgres.py

The script is idempotent — re-running it skips rows that already exist.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import redis as redis_lib

from config.settings import get_settings
from infra import postgres as pg

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _get_redis() -> redis_lib.Redis:
    cfg = get_settings().redis
    return redis_lib.Redis(
        host=cfg.host,
        port=cfg.port,
        password=cfg.password or None,
        db=cfg.db,
        decode_responses=True,
    )


def migrate() -> None:
    r = _get_redis()

    pg.run_migrations()
    logger.info("Postgres migrations applied.")

    kb_ids: set[str] = r.smembers("kbs")
    logger.info("Found %d KBs in Redis.", len(kb_ids))

    for kb_id in sorted(kb_ids):
        meta = r.hgetall(f"kb:{kb_id}")
        description = meta.get("description", "")

        pg.register_kb(kb_id, description)
        logger.info("KB migrated: %s", kb_id)

        doc_keys: set[str] = r.smembers(f"docs:{kb_id}")
        logger.info("  %d documents in KB %s", len(doc_keys), kb_id)

        for object_key in sorted(doc_keys):
            doc = r.hgetall(f"doc:{kb_id}:{object_key}")
            if not doc:
                continue

            # Build fields dict — only include non-empty values
            fields: dict = {}
            for field in ("status", "etag", "run_id", "updated_at", "error",
                          "doc_type", "embedding_model", "doc_created_at"):
                val = doc.get(field, "")
                if val:
                    fields[field] = val

            for int_field in ("chunk_count", "file_size"):
                val = doc.get(int_field, "")
                if val:
                    try:
                        fields[int_field] = int(val)
                    except ValueError:
                        pass

            if not fields.get("status"):
                fields["status"] = "indexed"

            # Also check standalone ETag key
            etag_key = r.get(f"etag:{kb_id}:{object_key}")
            if etag_key and not fields.get("etag"):
                fields["etag"] = etag_key

            pg.set_doc_status(kb_id, object_key, fields)
            logger.info("  Doc migrated: %s/%s status=%s", kb_id, object_key, fields.get("status"))

    logger.info("Migration complete.")


if __name__ == "__main__":
    migrate()
