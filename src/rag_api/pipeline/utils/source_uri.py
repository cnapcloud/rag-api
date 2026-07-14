"""source_uri normalization utilities (R-02).

Normalization ensures that the same document always produces the same source_uri
regardless of how it is referenced, enabling reliable dedup via UNIQUE(kb_id, source_uri).
"""

from __future__ import annotations

import unicodedata
from urllib.parse import ParseResult, parse_qs, unquote, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref",
})


def _normalize_web_url(url: str) -> str:
    p: ParseResult = urlparse(url)
    scheme = "https"
    netloc = p.netloc.lower()
    # urlparse leaves the path exactly as it appeared in the source string, so
    # a raw-Hangul link (admin-typed seed URL) and a percent-encoded link
    # (BFS-discovered <a href>, common on MediaWiki-style sites) normalize to
    # two different strings for the same page unless decoded first. NFC also
    # collapses composed vs. decomposed Hangul, which is otherwise invisible
    # in a browser address bar but differs byte-for-byte.
    path = unicodedata.normalize("NFC", unquote(p.path, encoding="utf-8", errors="replace"))
    path = path.rstrip("/") or "/"
    params = {
        unicodedata.normalize("NFC", k): [unicodedata.normalize("NFC", v) for v in vs]
        for k, vs in parse_qs(p.query, keep_blank_values=True).items()
        if k not in _TRACKING_PARAMS
    }
    query = urlencode(sorted(params.items()), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def _normalize_github_url(url: str) -> str:
    # https://github.com/{owner}/{repo}/blob/{branch}/{path}
    # GitHub owner/repo names are case-insensitive; lowercase for stable dedup.
    p: ParseResult = urlparse(url)
    parts = p.path.lstrip("/").split("/", 2)
    if len(parts) >= 2:
        parts[0] = parts[0].lower()
        parts[1] = parts[1].lower()
        new_path = "/" + "/".join(parts)
        return urlunparse(("https", p.netloc.lower(), new_path, "", "", ""))
    return url


def normalize_source_uri(source_type: str, raw: str) -> str:
    """Return the canonical source_uri for a given source_type and raw identifier.

    Rules per source type:
      s3:         no normalization (filename is controlled by the API)
      web:        https, lowercase host, strip trailing slash, strip fragment,
                  remove tracking params, sort remaining query params
      confluence: same as web (Confluence page URLs are standard https URLs)
      github:     https, lowercase owner and repo, strip fragment
    """
    if source_type == "s3":
        return raw

    if source_type in ("web", "confluence"):
        return _normalize_web_url(raw)

    if source_type == "github":
        return _normalize_github_url(raw)

    return raw
