"""ConfluenceConnector — fetches pages and attachments from a Confluence space (R-10)."""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Iterator

import httpx

from exceptions import ConfigError
from pipeline.ops.parse import SUPPORTED_EXTENSIONS
from pipeline.utils.source_uri import normalize_source_uri

logger = logging.getLogger(__name__)

_API_PAGE_LIMIT = 50


class ConfluenceConnector:
    """Connector for Confluence Cloud and Server (source_type=confluence).

    Config keys:
      base_url            str        Required. e.g. "https://company.atlassian.net"
      space_key           str        Required. Space key to sync (e.g. "DEV")
      auth_token_secret   str        Optional. Env var name holding the token.
                                     Cloud: email:api_token (colon-separated) -> Basic auth.
                                     Server: PAT string -> Bearer auth.
      exclude_labels      list[str]  Labels that cause a page (and its attachments) to be skipped.
      max_attachment_mb   int        Max attachment size in MB (default 10).
      request_delay_ms    int        Milliseconds to sleep between API calls (default 100).
      request_timeout_sec int        HTTP timeout in seconds (default 30).
    """

    def __init__(self, config: dict) -> None:
        self.base_url: str = config.get("base_url", "").rstrip("/")
        if not self.base_url:
            raise ConfigError("ConfluenceConnector requires base_url in config")
        self.space_key: str = config.get("space_key", "")
        if not self.space_key:
            raise ConfigError("ConfluenceConnector requires space_key in config")

        self.exclude_labels: frozenset[str] = frozenset(
            label.lower() for label in config.get("exclude_labels", [])
        )
        self.max_pages: int = int(config.get("max_pages", 50))
        depth_val = config.get("depth")
        self.depth: int | None = None if depth_val is None else int(depth_val)
        max_mb: int = int(config.get("max_attachment_mb", 10))
        self.max_attachment_bytes: int = max_mb * 1024 * 1024
        self.request_delay_ms: int = int(config.get("request_delay_ms", 100))
        self.timeout: int = int(config.get("request_timeout_sec", 30))

        token: str | None = config.get("auth_token_secret") or None
        if token and ":" in token:
            encoded = base64.b64encode(token.encode()).decode()
            self._auth_header: str | None = f"Basic {encoded}"
        elif token:
            self._auth_header = f"Bearer {token}"
        else:
            self._auth_header = None

    @property
    def _api_base(self) -> str:
        if ".atlassian.net" in self.base_url:
            return f"{self.base_url}/wiki/rest/api"
        return f"{self.base_url}/rest/api"

    def _make_download_url(self, relative_url: str) -> str:
        if relative_url.startswith("http"):
            return relative_url
        if ".atlassian.net" in self.base_url:
            return f"{self.base_url}/wiki{relative_url}"
        return f"{self.base_url}{relative_url}"

    def _page_url(self, page: dict) -> str:
        webui = page.get("_links", {}).get("webui", "")
        if webui:
            return f"{self.base_url}{webui}"
        page_id = page["id"]
        return f"{self.base_url}/spaces/{self.space_key}/pages/{page_id}"

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Accept": "application/json"}
        if self._auth_header:
            h["Authorization"] = self._auth_header
        return h

    def _api_get(self, client: httpx.Client, path: str, params: dict | None = None) -> dict:
        """GET {_api_base}/{path} with rate-limit sleep before the call."""
        if self.request_delay_ms > 0:
            time.sleep(self.request_delay_ms / 1000)
        resp = client.get(f"{self._api_base}/{path}", params=params or {})
        resp.raise_for_status()
        return resp.json()

    def sync(self, kb_id: str, connector_id: str) -> None:
        """Run Flow B for all pages (and their attachments) in the configured space."""
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers=self._headers(),
        ) as client:
            pages_total = 0
            for page in self._iter_pages(client):
                from connectors.abort import is_abort_requested
                if is_abort_requested(connector_id):
                    logger.info("Confluence sync aborted: connector_id=%s", connector_id)
                    break
                self._process_page(client, kb_id, connector_id, page)
                pages_total += 1

        logger.info(
            "Confluence sync done: connector_id=%s space=%s pages=%d max_pages=%d",
            connector_id,
            self.space_key,
            pages_total,
            self.max_pages,
        )

    def _iter_pages(self, client: httpx.Client) -> Iterator[dict]:
        start = 0
        fetched = 0
        while fetched < self.max_pages:
            batch = min(_API_PAGE_LIMIT, self.max_pages - fetched)
            data = self._api_get(
                client,
                "content",
                {
                    "spaceKey": self.space_key,
                    "type": "page",
                    "expand": "version,metadata.labels,body.view,ancestors,_links",
                    "limit": batch,
                    "start": start,
                },
            )
            results: list[dict] = data.get("results", [])
            yield from results
            fetched += len(results)
            if len(results) < batch:
                break
            start += batch

    def _has_excluded_label(self, page: dict) -> bool:
        if not self.exclude_labels:
            return False
        labels = page.get("metadata", {}).get("labels", {}).get("results", [])
        return any(label.get("name", "").lower() in self.exclude_labels for label in labels)

    def _process_page(
        self,
        client: httpx.Client,
        kb_id: str,
        connector_id: str,
        page: dict,
    ) -> None:
        """Flow B step [3] for one Confluence page and its attachments."""
        from infra.postgres import create_doc, get_doc_by_source
        from infra.s3 import upload_object
        from pipeline.queue.enqueue import enqueue_upload_event
        from pipeline.utils.doc_state import set_fetch_failed, set_fetching, set_staged

        page_id: str = page["id"]
        title: str = page["title"]
        version: str = str(page["version"]["number"])
        source_uri = normalize_source_uri("confluence", self._page_url(page))

        if self.depth is not None:
            ancestor_count = len(page.get("ancestors", []))
            if ancestor_count > self.depth:
                logger.debug(
                    "Page skipped (depth exceeded): source_uri=%s ancestor_count=%d depth=%d",
                    source_uri,
                    ancestor_count,
                    self.depth,
                )
                return

        if self._has_excluded_label(page):
            logger.debug("Page excluded by label: source_uri=%s", source_uri)
            return

        doc = get_doc_by_source(kb_id, source_uri)

        if doc is not None and doc.get("status") != "deleted":
            aborted = doc.get("status") == "failed" and "Aborted" in (doc.get("error") or "")
            if doc.get("content_version") == version and not aborted:
                logger.info("Page unchanged: source_uri=%s version=%s", source_uri, version)
                self._process_page_attachments(client, kb_id, connector_id, page_id)
                return

        if doc is None:
            doc = create_doc(
                kb_id=kb_id,
                source=source_uri,
                title=title,
                source_type="confluence",
                status="fetching",
                connector_id=connector_id,
                doc_type="html",
            )
        else:
            set_fetching(doc["doc_id"], connector_id=connector_id)

        doc_id: str = doc["doc_id"]
        html_body: str = page.get("body", {}).get("view", {}).get("value", "")
        file_bytes = html_body.encode("utf-8")
        storage_key = f"{kb_id}/confluence/{doc_id}.html"

        try:
            upload_object(
                kb_id,
                f"confluence/{doc_id}.html",
                file_bytes,
                content_type="text/html",
                metadata={
                    "doc-id": doc_id,
                    "kb-id": kb_id,
                    "source-type": "confluence",
                    "source-uri": source_uri,
                },
            )
        except Exception as e:
            set_fetch_failed(doc_id, str(e))
            logger.warning("S3 stage failed for page: source_uri=%s err=%s", source_uri, e)
            self._process_page_attachments(client, kb_id, connector_id, page_id)
            return

        set_staged(doc_id, title=title, storage_key=storage_key, content_version=version, file_size=len(file_bytes))
        enqueue_upload_event(doc_id, force=False)
        logger.info(
            "Confluence page staged: source_uri=%s doc_id=%s title=%r",
            source_uri,
            doc_id,
            title,
        )
        self._process_page_attachments(client, kb_id, connector_id, page_id)

    def _iter_attachments(self, client: httpx.Client, page_id: str) -> Iterator[dict]:
        start = 0
        while True:
            data = self._api_get(
                client,
                f"content/{page_id}/child/attachment",
                {"expand": "version", "limit": _API_PAGE_LIMIT, "start": start},
            )
            results: list[dict] = data.get("results", [])
            yield from results
            if len(results) < _API_PAGE_LIMIT:
                break
            start += _API_PAGE_LIMIT

    def _process_page_attachments(
        self,
        client: httpx.Client,
        kb_id: str,
        connector_id: str,
        page_id: str,
    ) -> None:
        try:
            for attachment in self._iter_attachments(client, page_id):
                try:
                    self._process_attachment(client, kb_id, connector_id, attachment)
                except Exception as e:
                    logger.error(
                        "Unhandled error processing attachment: page_id=%s att_id=%s err=%s",
                        page_id,
                        attachment.get("id", "?"),
                        e,
                    )
        except Exception as e:
            logger.error(
                "Failed to list attachments for page: page_id=%s err=%s", page_id, e
            )

    def _process_attachment(
        self,
        client: httpx.Client,
        kb_id: str,
        connector_id: str,
        attachment: dict,
    ) -> None:
        """Flow B step [3] for one Confluence attachment."""
        from infra.postgres import create_doc, get_doc_by_source
        from infra.s3 import upload_object
        from pipeline.queue.enqueue import enqueue_upload_event
        from pipeline.utils.doc_state import set_fetch_failed, set_fetching, set_staged

        title: str = attachment["title"]
        ext = Path(title).suffix.lower()

        if ext not in SUPPORTED_EXTENSIONS:
            logger.debug(
                "Attachment skipped (unsupported format): title=%s ext=%s", title, ext
            )
            return

        file_size = int(attachment.get("extensions", {}).get("fileSize") or 0)
        if file_size > self.max_attachment_bytes:
            logger.info(
                "Attachment skipped (too large): title=%s size_mb=%.1f max_mb=%.1f",
                title,
                file_size / 1024 / 1024,
                self.max_attachment_bytes / 1024 / 1024,
            )
            return

        att_id: str = attachment["id"]
        version: str = str(attachment["version"]["number"])
        download_path: str = attachment.get("_links", {}).get("download", "")
        if not download_path:
            logger.warning("Attachment skipped (no download link): title=%s id=%s", title, att_id)
            return
        download_url = self._make_download_url(download_path)
        source_uri = normalize_source_uri("confluence", download_url)

        doc = get_doc_by_source(kb_id, source_uri)

        if doc is not None and doc.get("status") != "deleted":
            aborted = doc.get("status") == "failed" and "Aborted" in (doc.get("error") or "")
            if doc.get("content_version") == version and not aborted:
                logger.info("Attachment unchanged: source_uri=%s", source_uri)
                return

        if doc is None:
            doc = create_doc(
                kb_id=kb_id,
                source=source_uri,
                title=title,
                source_type="confluence",
                status="fetching",
                connector_id=connector_id,
                doc_type=ext.lstrip("."),
            )
        else:
            set_fetching(doc["doc_id"], connector_id=connector_id)

        doc_id: str = doc["doc_id"]

        try:
            if self.request_delay_ms > 0:
                time.sleep(self.request_delay_ms / 1000)
            resp = client.get(download_url)
            resp.raise_for_status()
            content = resp.content
        except Exception as e:
            set_fetch_failed(doc_id, str(e))
            logger.warning(
                "Attachment download failed: source_uri=%s err=%s", source_uri, e
            )
            return

        media_type: str = (
            attachment.get("metadata", {}).get("mediaType") or "application/octet-stream"
        )
        storage_key = f"{kb_id}/confluence/{doc_id}{ext}"

        try:
            upload_object(
                kb_id,
                f"confluence/{doc_id}{ext}",
                content,
                content_type=media_type,
                metadata={
                    "doc-id": doc_id,
                    "kb-id": kb_id,
                    "source-type": "confluence",
                    "source-uri": source_uri,
                },
            )
        except Exception as e:
            set_fetch_failed(doc_id, str(e))
            logger.warning(
                "S3 stage failed for attachment: source_uri=%s err=%s", source_uri, e
            )
            return

        set_staged(doc_id, title=title, storage_key=storage_key, content_version=version, file_size=len(content))
        enqueue_upload_event(doc_id, force=False)
        logger.info(
            "Confluence attachment staged: source_uri=%s doc_id=%s title=%r",
            source_uri,
            doc_id,
            title,
        )
