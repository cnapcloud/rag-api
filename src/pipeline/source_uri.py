"""source_uri normalization utilities (R-02).

Normalization ensures that the same document always produces the same source_uri
regardless of how it is referenced, enabling reliable dedup via UNIQUE(kb_id, source_uri).
"""

from __future__ import annotations

from urllib.parse import ParseResult, parse_qs, urlencode, urlparse, urlunparse

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref",
})


def _normalize_web_url(url: str) -> str:
    p: ParseResult = urlparse(url)
    scheme = "https"
    netloc = p.netloc.lower()
    path = p.path.rstrip("/") or "/"
    params = {k: v for k, v in parse_qs(p.query, keep_blank_values=True).items()
              if k not in _TRACKING_PARAMS}
    query = urlencode(sorted(params.items()), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def normalize_source_uri(source_type: str, raw: str) -> str:
    """Return the canonical source_uri for a given source_type and raw identifier.

    Rules per source type:
      s3:         no normalization (filename is controlled by the API)
      web:        https, lowercase host, strip trailing slash, strip fragment,
                  remove tracking params, sort remaining query params
      confluence: confluence://{space}/{page_id} — lowercase space key
      github:     github://{owner}/{repo}/{ref}/{path} — lowercase owner and repo
    """
    if source_type == "s3":
        return raw

    if source_type == "web":
        return _normalize_web_url(raw)

    if source_type == "confluence":
        prefix = "confluence://"
        if raw.startswith(prefix):
            rest = raw[len(prefix):]
            parts = rest.split("/", 1)
            if len(parts) == 2:
                return f"{prefix}{parts[0].lower()}/{parts[1]}"
        return raw.lower()

    if source_type == "github":
        prefix = "github://"
        if raw.startswith(prefix):
            rest = raw[len(prefix):]
            parts = rest.split("/", 3)
            if len(parts) >= 2:
                parts[0] = parts[0].lower()
                parts[1] = parts[1].lower()
                return prefix + "/".join(parts)
        return raw

    return raw
