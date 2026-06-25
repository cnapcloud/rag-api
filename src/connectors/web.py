"""WebConnector — crawls seed URLs and stages HTML pages for pipeline ingestion (R-09)."""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from fnmatch import fnmatch
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from exceptions import ConfigError
from pipeline.source_uri import normalize_source_uri

logger = logging.getLogger(__name__)

_USER_AGENT = "RAG-WebConnector/1.0"

# BFS queue is capped at this multiple of max_pages to prevent memory bloat
# when a portal page links to thousands of subpages.
_QUEUE_SIZE_MULTIPLIER = 20

_PAGINATION_PATH_RE = re.compile(r"/page/\d+(/|$)", re.IGNORECASE)
_PAGINATION_QUERY_RE = re.compile(r"(?:^|&)(page|p)=\d+")


def _is_pagination_url(url: str) -> bool:
    """Return True if the URL looks like a paginated index page."""
    p = urlparse(url)
    if _PAGINATION_PATH_RE.search(p.path):
        return True
    if p.query and _PAGINATION_QUERY_RE.search(p.query):
        return True
    return False


def _has_sufficient_content(html: str, min_chars: int) -> bool:
    """Return True if trafilatura extracts at least min_chars of content from html.

    Fails open — returns True on extraction errors so pages are not silently dropped.
    """
    if min_chars <= 0:
        return True
    try:
        import trafilatura

        extracted = trafilatura.extract(html)
        return bool(extracted) and len(extracted) >= min_chars
    except Exception:
        return True


def _extract_title(html: str, fallback: str) -> str:
    """Return page title from HTML using priority order:
    og:title -> article h1 -> h1 -> <title> -> fallback URL.
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        og = soup.select_one('meta[property="og:title"]')
        if og and og.get("content"):
            return str(og["content"]).strip()

        article_h1 = soup.select_one("article h1")
        if article_h1:
            text = article_h1.get_text(strip=True)
            if text:
                return text

        h1 = soup.select_one("h1")
        if h1:
            text = h1.get_text(strip=True)
            if text:
                return text

        tag = soup.find("title")
        if tag and tag.string:
            return tag.string.strip()
    except Exception:
        pass

    return fallback


def _discover_links(html: str, base_url: str) -> list[str]:
    """Extract absolute http(s) links from HTML for BFS crawl."""
    try:
        from bs4 import BeautifulSoup

        links = []
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#"):
                continue
            abs_url = urljoin(base_url, href)
            if abs_url.startswith("http"):
                links.append(abs_url)
        return links
    except Exception:
        return []


def _seed_prefix(url: str) -> str:
    """Return scheme+netloc+path with no trailing slash, query, or fragment."""
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))


class WebConnector:
    """Connector for web pages (source_type=web).

    Config keys (all optional except seed_urls):
      seed_urls           list[str]  Required. Starting URLs. Path in URL is used as
                                     scope prefix — only URLs under that path are crawled.
      depth               int        BFS depth limit (default 2).
      include_patterns    list[str]  fnmatch patterns — additional filter within seed scope.
      exclude_patterns    list[str]  fnmatch patterns — always skip matching URLs.
      max_pages           int        Hard limit on pages processed per sync (default 50).
      request_timeout_sec int        HTTP timeout in seconds (default 30).
      request_delay_ms    int        Milliseconds to sleep between page fetches (default 0).
      skip_seed_pages     bool       Depth-0 pages (seed URLs) are crawled for links but
                                     not staged as documents (default True).
      min_content_chars   int        Pages where trafilatura extracts fewer than this many
                                     characters are skipped from staging (default 200).
                                     Set to 0 to disable.
    """

    def __init__(self, config: dict) -> None:
        self.seed_urls: list[str] = config.get("seed_urls", [])
        if not self.seed_urls:
            raise ConfigError("WebConnector requires at least one seed_url in config")
        self.depth: int = int(config.get("depth", 2))
        self.include_patterns: list[str] = config.get("include_patterns", [])
        self.exclude_patterns: list[str] = config.get("exclude_patterns", [])
        self.max_pages: int = int(config.get("max_pages", 50))
        self.timeout: int = int(config.get("request_timeout_sec", 30))
        self.request_delay_ms: int = int(config.get("request_delay_ms", 100))
        self.skip_seed_pages: bool = bool(config.get("skip_seed_pages", True))
        self.min_content_chars: int = int(config.get("min_content_chars", 200))
        self.auth_headers: dict[str, str] = config.get("auth_headers") or {}
        self.auth_basic: tuple[str, str] | None = (
            (str(cfg["username"]), str(cfg["password"]))
            if (cfg := config.get("auth_basic"))
            else None
        )

        # Scope is derived from the full path of each seed URL.
        # https://example.com/docs → only https://example.com/docs/* is crawled.
        # https://example.com     → full domain is allowed.
        self._seed_prefixes: frozenset[str] = frozenset(
            _seed_prefix(url) for url in self.seed_urls if url
        )

    def sync(self, kb_id: str, connector_id: str) -> None:
        """Run Flow B for all pages reachable from seed_urls."""
        visited: set[str] = set()
        queued: set[str] = set()
        queue: deque[tuple[str, int]] = deque()
        max_queue_size = self.max_pages * _QUEUE_SIZE_MULTIPLIER

        for url in self.seed_urls:
            norm = normalize_source_uri("web", url)
            queue.append((norm, 0))
            queued.add(norm)

        pages_processed = 0

        client_kwargs: dict = {
            "timeout": self.timeout,
            "follow_redirects": True,
            "headers": {"User-Agent": _USER_AGENT},
        }
        if self.auth_headers:
            client_kwargs["headers"] = {"User-Agent": _USER_AGENT, **self.auth_headers}
        elif self.auth_basic:
            client_kwargs["auth"] = self.auth_basic

        with httpx.Client(**client_kwargs) as client:
            while queue and pages_processed < self.max_pages:
                source_uri, current_depth = queue.popleft()

                if source_uri in visited:
                    continue
                visited.add(source_uri)

                if not self._should_process(source_uri):
                    logger.debug("URL filtered out: %s", source_uri)
                    continue

                if self.request_delay_ms > 0 and pages_processed > 0:
                    time.sleep(self.request_delay_ms / 1000)

                html = self._process_page(client, kb_id, connector_id, source_uri, current_depth)
                pages_processed += 1

                if html is not None and current_depth < self.depth:
                    for link in _discover_links(html, source_uri):
                        norm_link = normalize_source_uri("web", link)
                        if norm_link not in queued and len(queue) < max_queue_size:
                            queue.append((norm_link, current_depth + 1))
                            queued.add(norm_link)

        logger.info(
            "Web connector sync done: connector_id=%s pages_processed=%d",
            connector_id,
            pages_processed,
        )

    def _should_process(self, url: str) -> bool:
        """Return False if URL is outside seed scope or matches an exclude pattern.

        Pagination pages are NOT filtered here — they are fetched for link discovery
        but skipped from staging inside _process_page (same pattern as skip_seed_pages).
        """
        # Exclude patterns always win.
        for pat in self.exclude_patterns:
            if fnmatch(url, pat):
                return False

        # Must fall under at least one seed URL's path scope.
        p = urlparse(url)
        base = urlunparse((p.scheme, p.netloc, p.path, "", "", ""))
        if not any(base == prefix or base.startswith(prefix + "/") for prefix in self._seed_prefixes):
            return False

        # include_patterns is an additional filter within scope.
        if self.include_patterns:
            return any(fnmatch(url, pat) for pat in self.include_patterns)

        return True

    def _process_page(
        self,
        client: httpx.Client,
        kb_id: str,
        connector_id: str,
        source_uri: str,
        depth: int = 0,
    ) -> str | None:
        """Flow B step [3] for one page.

        Returns raw HTML if the page was fetched (for link discovery), None on hard failure.
        Unchanged pages and filtered pages return HTML but skip staging/enqueue.
        """
        from infra.postgres import create_doc, get_doc_by_source_uri, update_doc_fields
        from infra.s3 import upload_object
        from pipeline.enqueue import enqueue_upload_event

        doc = get_doc_by_source_uri(kb_id, source_uri)

        # [3-2] Fetch content — always GET so we can discover links from unchanged pages.
        try:
            resp = client.get(source_uri)
            resp.raise_for_status()
        except Exception as e:
            err_msg = str(e)[:500]
            if doc is None:
                doc = create_doc(
                    kb_id=kb_id,
                    source_uri=source_uri,
                    source=source_uri,
                    source_type="web",
                    status="failed",
                    connector_id=connector_id,
                    doc_type="html",
                )
                update_doc_fields(doc["doc_id"], {"error": err_msg})
            else:
                update_doc_fields(doc["doc_id"], {"status": "failed", "error": err_msg, "connector_id": connector_id})
            logger.warning("Failed to fetch page: source_uri=%s err=%s", source_uri, e)
            return None

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type:
            logger.debug("Skipping non-HTML response: source_uri=%s content_type=%s", source_uri, content_type)
            return None

        html = resp.text
        etag = resp.headers.get("etag", "").strip('"')

        # Depth-0 pages are seed/index pages — crawl their links but don't stage.
        if self.skip_seed_pages and depth == 0:
            logger.debug("Seed page skipped from staging: source_uri=%s", source_uri)
            return html

        # Pagination pages (/page/2/, ?page=3) are index pages — crawl their links but don't stage.
        if _is_pagination_url(source_uri):
            logger.debug("Pagination page skipped from staging: source_uri=%s", source_uri)
            return html

        # Skip pages with insufficient extractable content (nav/index/error pages).
        if not _has_sufficient_content(html, self.min_content_chars):
            logger.debug(
                "Insufficient content page skipped: source_uri=%s min_chars=%d",
                source_uri,
                self.min_content_chars,
            )
            return html

        # [3-1] Compare content_version for existing non-deleted docs.
        if doc is not None and doc.get("status") != "deleted":
            stored = doc.get("content_version") or ""
            if etag and etag == stored:
                fields: dict = {}
                if doc.get("connector_id") != connector_id:
                    fields["connector_id"] = connector_id
                new_title = _extract_title(html, source_uri)
                if new_title != doc.get("source"):
                    fields["source"] = new_title
                    logger.info(
                        "Title updated on unchanged page: source_uri=%s title=%r",
                        source_uri,
                        new_title,
                    )
                else:
                    logger.info("Page unchanged (ETag match): source_uri=%s", source_uri)
                if fields:
                    update_doc_fields(doc["doc_id"], fields)
                return html  # Return HTML for link discovery; skip staging.

        # Create or set status=fetching.
        if doc is None:
            doc = create_doc(
                kb_id=kb_id,
                source_uri=source_uri,
                source=source_uri,
                source_type="web",
                status="fetching",
                connector_id=connector_id,
                doc_type="html",
            )
        else:
            update_doc_fields(doc["doc_id"], {"status": "fetching", "connector_id": connector_id})

        doc_id = doc["doc_id"]
        title = _extract_title(html, source_uri)

        # [3-3] Stage raw HTML to object storage.
        storage_key = f"{kb_id}/web/{doc_id}.html"
        file_bytes = html.encode("utf-8")
        try:
            upload_object(
                kb_id,
                f"web/{doc_id}.html",
                file_bytes,
                content_type="text/html",
                metadata={
                    "doc-id": doc_id,
                    "kb-id": kb_id,
                    "source-type": "web",
                    "source-uri": source_uri,
                },
            )
        except Exception as e:
            update_doc_fields(doc_id, {"status": "failed", "error": str(e)[:500]})
            logger.warning("S3 stage failed: source_uri=%s err=%s", source_uri, e)
            return html  # Return HTML for link discovery even on stage failure.

        # [3-4] Update doc.
        update_doc_fields(
            doc_id,
            {
                "source": title,
                "status": "pending",
                "storage_key": storage_key,
                "content_version": etag or None,
                "file_size": len(file_bytes),
            },
        )

        # [3-5] Enqueue.
        enqueue_upload_event(doc_id, force=False)
        logger.info(
            "Web page staged: source_uri=%s doc_id=%s title=%r",
            source_uri,
            doc_id,
            title,
        )
        return html
