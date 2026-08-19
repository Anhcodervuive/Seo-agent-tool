"""Validation and normalization helpers for LibreCrawl exports.

LibreCrawl is an external service, so its payload is treated as untrusted
input.  These helpers keep provider-specific cleanup out of the database
persistence code and make the data contract easy to test independently.
"""

from copy import deepcopy
from urllib.parse import urlsplit, urlunsplit


def normalize_url(value):
    """Return a stable URL representation, or ``None`` for unusable input."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None

    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return value.rstrip("/") or None

    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    if not hostname:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, parts.query, ""))


def _as_dict(value):
    return deepcopy(value) if isinstance(value, dict) else {}


def _as_list(value):
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    return [value]


def _text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize_crawl_export(payload):
    """Normalize a raw crawl payload into safe, deduplicated collections.

    Invalid rows are skipped rather than aborting an otherwise useful crawl.
    The returned counters describe persisted candidates, allowing the caller
    to expose data-quality information in snapshot notes.
    """
    payload = payload if isinstance(payload, dict) else {}
    raw_urls = _as_list(payload.get("urls"))
    raw_links = _as_list(payload.get("links"))
    raw_issues = _as_list(payload.get("issues"))
    urls = []
    seen_urls = set()
    invalid_urls = 0
    duplicate_urls = 0
    for raw in raw_urls:
        if not isinstance(raw, dict):
            invalid_urls += 1
            continue
        item = _as_dict(raw)
        item["url"] = normalize_url(item.get("url"))
        if not item["url"]:
            invalid_urls += 1
            continue
        if item["url"] in seen_urls:
            duplicate_urls += 1
            continue
        seen_urls.add(item["url"])
        item["canonical_url"] = normalize_url(item.get("canonical_url"))
        item["linked_from"] = [u for u in (normalize_url(v) for v in _as_list(item.get("linked_from"))) if u]
        item["external_links"] = max(0, int(item["external_links"])) if str(item.get("external_links", "")).strip().lstrip("-").isdigit() else item.get("external_links")
        item["internal_links"] = max(0, int(item["internal_links"])) if str(item.get("internal_links", "")).strip().lstrip("-").isdigit() else item.get("internal_links")
        urls.append(item)

    links = []
    seen_links = set()
    invalid_links = 0
    duplicate_links = 0
    for raw in raw_links:
        if not isinstance(raw, dict):
            invalid_links += 1
            continue
        item = _as_dict(raw)
        item["source_url"] = normalize_url(item.get("source_url"))
        item["target_url"] = normalize_url(item.get("target_url"))
        if not item["source_url"] or not item["target_url"]:
            invalid_links += 1
            continue
        key = (item["source_url"], item["target_url"], _text(item.get("anchor_text")))
        if key in seen_links:
            duplicate_links += 1
            continue
        seen_links.add(key)
        links.append(item)

    issues = []
    seen_issues = set()
    invalid_issues = 0
    duplicate_issues = 0
    for raw in raw_issues:
        if not isinstance(raw, dict):
            invalid_issues += 1
            continue
        item = _as_dict(raw)
        item["url"] = normalize_url(item.get("url"))
        item["issue"] = _text(item.get("issue"))
        item["issue_type"] = _text(item.get("type") or item.get("issue_type"))
        item["category"] = _text(item.get("category"))
        if not item["issue"]:
            invalid_issues += 1
            continue
        key = (item["url"], item["issue"], item["issue_type"], item["category"])
        if key in seen_issues:
            duplicate_issues += 1
            continue
        seen_issues.add(key)
        issues.append(item)

    return {
        "urls": urls,
        "links": links,
        "issues": issues,
        "quality": {
            "raw_urls": len(raw_urls),
            "raw_links": len(raw_links),
            "raw_issues": len(raw_issues),
            "valid_urls": len(urls),
            "valid_links": len(links),
            "valid_issues": len(issues),
            "invalid_urls_removed": invalid_urls,
            "invalid_links_removed": invalid_links,
            "invalid_issues_removed": invalid_issues,
            "duplicate_urls_removed": duplicate_urls,
            "duplicate_links_removed": duplicate_links,
            "duplicate_issues_removed": duplicate_issues,
        },
    }
