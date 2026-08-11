"""Helpers for accepting and storing website URLs consistently."""

from urllib.parse import urlsplit


def normalize_site_url(value, default_scheme="https"):
    """Return a canonical site origin such as ``https://example.com``."""
    raw_value = (value or "").strip()
    if not raw_value:
        raise ValueError("A website domain or URL is required.")

    candidate = raw_value if "://" in raw_value else f"{default_scheme}://{raw_value}"
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Invalid website URL: {raw_value}")
    if parsed.username or parsed.password:
        raise ValueError("Website URLs must not contain username or password information.")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid website URL: {raw_value}") from exc

    hostname = parsed.hostname.rstrip(".").lower()
    netloc = hostname if port is None else f"{hostname}:{port}"
    return f"{parsed.scheme.lower()}://{netloc}"
