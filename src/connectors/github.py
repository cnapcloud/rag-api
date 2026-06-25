"""GitHubConnector — fetches source files from a GitHub repository (R-11)."""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path

import httpx

from exceptions import ConfigError
from pipeline.ops.parse import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_MAX_FILE_SIZE_DEFAULT_MB = 5


class GitHubConnector:
    """Connector for GitHub repositories (source_type=github).

    Config keys:
      owner               str  Required. Repository owner (user or org).
      repo                str  Required. Repository name.
      branch              str  Branch to sync (default "main").
      path_prefix         str  Optional. Only include files under this path prefix.
      auth_token_secret   str  Optional. Env var name holding a GitHub PAT.
      max_file_size_mb    int  Max file size to download in MB (default 5).
      request_delay_ms    int  Milliseconds to sleep between API calls (default 100).
      max_files           int  Max number of files to sync per run (default 200).
      request_timeout_sec int  HTTP timeout in seconds (default 30).
    """

    def __init__(self, config: dict) -> None:
        self.owner: str = config.get("owner", "").strip()
        if not self.owner:
            raise ConfigError("GitHubConnector requires owner in config")
        self.repo: str = config.get("repo", "").strip()
        if not self.repo:
            raise ConfigError("GitHubConnector requires repo in config")

        self.branch: str = config.get("branch", "main").strip()
        self.path_prefix: str = config.get("path_prefix", "").lstrip("/")
        self.max_files: int = int(config.get("max_files", 200))
        self.max_file_bytes: int = int(config.get("max_file_size_mb", _MAX_FILE_SIZE_DEFAULT_MB)) * 1024 * 1024
        self.request_delay_ms: int = int(config.get("request_delay_ms", 100))
        self.timeout: int = int(config.get("request_timeout_sec", 30))

        auth_secret = config.get("auth_token_secret")
        token = os.environ.get(auth_secret) if auth_secret else None
        self._auth_header: str | None = f"Bearer {token}" if token else None

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._auth_header:
            h["Authorization"] = self._auth_header
        return h

    def _api_get(self, client: httpx.Client, path: str, params: dict | None = None) -> dict | list:
        if self.request_delay_ms > 0:
            time.sleep(self.request_delay_ms / 1000)
        resp = client.get(f"{_GITHUB_API}/{path}", params=params or {})
        resp.raise_for_status()
        return resp.json()

    def _get_tree_sha(self, client: httpx.Client) -> str:
        data = self._api_get(client, f"repos/{self.owner}/{self.repo}/branches/{self.branch}")
        assert isinstance(data, dict)
        return data["commit"]["commit"]["tree"]["sha"]

    def _iter_blobs(self, client: httpx.Client) -> list[dict]:
        tree_sha = self._get_tree_sha(client)
        data = self._api_get(
            client,
            f"repos/{self.owner}/{self.repo}/git/trees/{tree_sha}",
            {"recursive": "1"},
        )
        assert isinstance(data, dict)
        items: list[dict] = data.get("tree", [])
        blobs = [
            item for item in items
            if item.get("type") == "blob"
            and (not self.path_prefix or item["path"].startswith(self.path_prefix))
            and Path(item["path"]).suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        return blobs[: self.max_files]

    def _download_file(self, client: httpx.Client, path: str) -> bytes:
        if self.request_delay_ms > 0:
            time.sleep(self.request_delay_ms / 1000)
        data = self._api_get(client, f"repos/{self.owner}/{self.repo}/contents/{path}", {"ref": self.branch})
        assert isinstance(data, dict)

        content_b64: str = data.get("content", "")
        if content_b64:
            return base64.b64decode(content_b64.replace("\n", ""))

        # large file (>1 MB) — use download_url
        download_url: str = data.get("download_url", "")
        if download_url:
            resp = client.get(download_url)
            resp.raise_for_status()
            return resp.content

        raise ValueError(f"No content available for: {path}")

    def sync(self, kb_id: str, connector_id: str) -> None:
        """Run Flow B for all supported source files in the repository."""
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self._headers(),
        ) as client:
            blobs = self._iter_blobs(client)
            total = len(blobs)
            logger.info(
                "GitHub sync started: connector_id=%s repo=%s/%s branch=%s files=%d",
                connector_id,
                self.owner,
                self.repo,
                self.branch,
                total,
            )
            for item in blobs:
                try:
                    self._process_file(client, kb_id, connector_id, item)
                except Exception as e:
                    logger.error(
                        "Unhandled error processing file: path=%s err=%s",
                        item.get("path", "?"),
                        e,
                    )

        logger.info(
            "GitHub sync done: connector_id=%s repo=%s/%s files=%d",
            connector_id,
            self.owner,
            self.repo,
            total,
        )

    def _process_file(
        self,
        client: httpx.Client,
        kb_id: str,
        connector_id: str,
        item: dict,
    ) -> None:
        """Flow B step [3] for one repository file."""
        from infra.postgres import create_doc, get_doc_by_source_uri, update_doc_fields
        from infra.s3 import upload_object
        from pipeline.enqueue import enqueue_upload_event

        path: str = item["path"]
        sha: str = item["sha"]
        file_size: int = item.get("size", 0)
        ext: str = Path(path).suffix.lower()
        source_uri = f"github://{self.owner}/{self.repo}/{self.branch}/{path}"

        if file_size > self.max_file_bytes:
            logger.info(
                "File skipped (too large): path=%s size_mb=%.1f max_mb=%.1f",
                path,
                file_size / 1024 / 1024,
                self.max_file_bytes / 1024 / 1024,
            )
            return

        doc = get_doc_by_source_uri(kb_id, source_uri)

        if doc is not None and doc.get("status") != "deleted":
            if doc.get("content_version") == sha:
                logger.info("File unchanged: source_uri=%s sha=%s", source_uri, sha)
                return

        if doc is None:
            doc = create_doc(
                kb_id=kb_id,
                source_uri=source_uri,
                source=path,
                source_type="github",
                status="fetching",
                connector_id=connector_id,
                doc_type=ext.lstrip("."),
            )
        else:
            update_doc_fields(doc["doc_id"], {"status": "fetching", "connector_id": connector_id})

        doc_id: str = doc["doc_id"]

        try:
            content = self._download_file(client, path)
        except Exception as e:
            update_doc_fields(doc_id, {"status": "failed", "error": str(e)[:500]})
            logger.warning("File download failed: source_uri=%s err=%s", source_uri, e)
            return

        storage_key = f"{kb_id}/github/{doc_id}{ext}"

        try:
            upload_object(
                kb_id,
                f"github/{doc_id}{ext}",
                content,
                content_type="text/plain",
                metadata={
                    "doc-id": doc_id,
                    "kb-id": kb_id,
                    "source-type": "github",
                    "source-uri": source_uri,
                },
            )
        except Exception as e:
            update_doc_fields(doc_id, {"status": "failed", "error": str(e)[:500]})
            logger.warning("S3 stage failed for file: source_uri=%s err=%s", source_uri, e)
            return

        update_doc_fields(
            doc_id,
            {
                "source": path,
                "status": "pending",
                "storage_key": storage_key,
                "content_version": sha,
                "file_size": len(content),
            },
        )
        enqueue_upload_event(doc_id, force=False)
        logger.info(
            "GitHub file staged: source_uri=%s doc_id=%s path=%r",
            source_uri,
            doc_id,
            path,
        )
