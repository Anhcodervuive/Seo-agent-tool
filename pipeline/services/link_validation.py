"""Bounded validation for crawl links whose targets were not fetched.

LibreCrawl can reuse the status of pages that were part of the crawl, but
external links and internal URLs outside the configured crawl scope often do
not have a status.  This module checks each unresolved HTTP(S) target once,
then copies the result to every source-page occurrence before persistence.
"""

from __future__ import annotations

import datetime
import ipaddress
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit

import requests

from services.crawl_data import normalize_url


USER_AGENT = "SEO-Copilot-Link-Validator/1.0"
_thread_local = threading.local()


def _status_code(value):
    try:
        return int(value) if value is not None and str(value).strip() else None
    except (TypeError, ValueError):
        return None


def _session():
    session = getattr(_thread_local, "link_validation_session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.5",
        })
        _thread_local.link_validation_session = session
    return session


def _target_is_safe(target_url, *, allow_private_hosts=False, resolver=socket.getaddrinfo):
    """Reject local/private destinations to prevent the validator becoming SSRF."""
    if allow_private_hosts:
        return True
    parsed = urlsplit(target_url)
    hostname = parsed.hostname
    if not hostname:
        return False
    try:
        literal = ipaddress.ip_address(hostname)
        return not (
            literal.is_private
            or literal.is_loopback
            or literal.is_link_local
            or literal.is_multicast
            or literal.is_reserved
            or literal.is_unspecified
        )
    except ValueError:
        pass

    try:
        addresses = {
            item[4][0]
            for item in resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            if item and len(item) > 4 and item[4]
        }
    except OSError:
        # Let the HTTP client produce the actionable DNS error classification.
        return True
    if not addresses:
        return True
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


def _connection_error_type(exc):
    message = str(exc).lower()
    if any(token in message for token in ("name resolution", "getaddrinfo", "no address associated", "nodename nor servname")):
        return "dns_error"
    if "refused" in message:
        return "connection_refused"
    if "network is unreachable" in message or "no route to host" in message:
        return "network_unreachable"
    return "connection_failed"


def _validate_target(target_url, *, timeout_seconds=10, allow_private_hosts=False):
    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    started_at = time.perf_counter()
    result = {
        "target_status": 0,
        "target_final_url": target_url,
        "target_status_source": "validator",
        "target_error_type": None,
        "target_error_message": None,
        "target_checked_at": checked_at,
        "target_response_time_ms": None,
        "target_redirect_count": 0,
    }
    if not _target_is_safe(target_url, allow_private_hosts=allow_private_hosts):
        result.update({
            "target_status": None,
            "target_status_source": "skipped",
            "target_error_type": "unsafe_target",
            "target_error_message": "Private, local, or reserved network targets are not requested.",
        })
        return result

    response = None
    try:
        response = _session().request(
            "HEAD",
            target_url,
            allow_redirects=True,
            timeout=(timeout_seconds, timeout_seconds),
        )
        # Some servers either reject HEAD or return a status that differs from
        # a real navigation.  Streamed GET verifies the failure without
        # downloading the response body.
        if response.status_code >= 400:
            response.close()
            response = _session().request(
                "GET",
                target_url,
                allow_redirects=True,
                stream=True,
                timeout=(timeout_seconds, timeout_seconds),
            )
        result.update({
            "target_status": response.status_code,
            "target_final_url": normalize_url(response.url) or str(response.url),
            "target_redirect_count": len(response.history),
        })
    except requests.Timeout as exc:
        result.update(target_error_type="timeout", target_error_message=str(exc)[:1000])
    except requests.exceptions.SSLError as exc:
        result.update(target_error_type="ssl_error", target_error_message=str(exc)[:1000])
    except requests.exceptions.TooManyRedirects as exc:
        result.update(target_error_type="too_many_redirects", target_error_message=str(exc)[:1000])
    except requests.exceptions.ConnectionError as exc:
        result.update(target_error_type=_connection_error_type(exc), target_error_message=str(exc)[:1000])
    except (requests.exceptions.InvalidURL, requests.exceptions.MissingSchema) as exc:
        result.update(target_error_type="malformed_url", target_error_message=str(exc)[:1000])
    except requests.RequestException as exc:
        result.update(target_error_type="request_error", target_error_message=str(exc)[:1000])
    finally:
        if response is not None:
            response.close()
        result["target_response_time_ms"] = int((time.perf_counter() - started_at) * 1000)
    return result


def enrich_crawl_link_statuses(
    payload,
    *,
    enabled=True,
    workers=12,
    per_host_workers=3,
    timeout_seconds=10,
    allow_private_hosts=False,
    validator=None,
):
    """Enrich unresolved link rows in-place and return coverage statistics."""
    started_at = time.perf_counter()
    payload = payload if isinstance(payload, dict) else {}
    links = payload.get("links") if isinstance(payload.get("links"), list) else []
    pages = payload.get("urls") if isinstance(payload.get("urls"), list) else []
    summary = {
        "enabled": bool(enabled),
        "link_rows": len(links),
        "unique_targets": 0,
        "crawler_status_targets": 0,
        "reused_page_targets": 0,
        "validated_targets": 0,
        "ok_targets": 0,
        "broken_targets": 0,
        "unreachable_targets": 0,
        "skipped_targets": 0,
        "workers": max(1, min(int(workers), 32)),
        "per_host_workers": max(1, min(int(per_host_workers), 8)),
        "timeout_seconds": max(1, min(int(timeout_seconds), 60)),
        "elapsed_ms": 0,
    }

    page_results = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_url = normalize_url(page.get("url"))
        if not page_url:
            continue
        status = _status_code(page.get("status_code"))
        if status is None and not page.get("error_type"):
            continue
        page_results[page_url] = {
            "target_status": status if status is not None else 0,
            "target_final_url": page_url,
            "target_status_source": "crawl",
            "target_error_type": page.get("error_type"),
            "target_error_message": page.get("error") or page.get("error_message"),
            "target_checked_at": page.get("crawled_at"),
            "target_response_time_ms": None,
            "target_redirect_count": len(page.get("redirects") or []),
        }

    unresolved = {}
    known_targets = set()
    crawler_status_targets = set()
    reused_page_targets = set()
    skipped_targets = set()
    for link in links:
        if not isinstance(link, dict):
            continue
        target_url = normalize_url(link.get("target_url"))
        if not target_url:
            continue
        known_targets.add(target_url)
        link["target_url"] = target_url
        existing_status = _status_code(link.get("target_status"))
        if existing_status is not None:
            link["target_status"] = existing_status
            link.setdefault("target_status_source", "crawler_export")
            crawler_status_targets.add(target_url)
            continue
        if target_url in page_results:
            link.update(page_results[target_url])
            reused_page_targets.add(target_url)
            continue
        parsed = urlsplit(target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            link.update({
                "target_status_source": "skipped",
                "target_error_type": "unsupported_scheme",
                "target_error_message": "Only HTTP and HTTPS links are validated.",
            })
            skipped_targets.add(target_url)
            continue
        unresolved.setdefault(target_url, []).append(link)

    summary["unique_targets"] = len(known_targets)
    summary["crawler_status_targets"] = len(crawler_status_targets)
    summary["reused_page_targets"] = len(reused_page_targets)
    summary["skipped_targets"] = len(skipped_targets)
    if not enabled or not unresolved:
        summary["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
        return summary

    validate = validator or _validate_target
    worker_count = max(1, min(int(workers), 32, len(unresolved)))
    per_host_workers = max(1, min(int(per_host_workers), worker_count))
    timeout_seconds = max(1, min(int(timeout_seconds), 60))
    host_semaphores = {
        urlsplit(target_url).hostname: threading.BoundedSemaphore(per_host_workers)
        for target_url in unresolved
    }

    def validate_with_host_limit(target_url):
        with host_semaphores[urlsplit(target_url).hostname]:
            return validate(
                target_url,
                timeout_seconds=timeout_seconds,
                allow_private_hosts=allow_private_hosts,
            )

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="link-check") as executor:
        futures = {
            executor.submit(validate_with_host_limit, target_url): target_url
            for target_url in unresolved
        }
        for future in as_completed(futures):
            target_url = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # One malformed target must not fail the audit.
                result = {
                    "target_status": 0,
                    "target_final_url": target_url,
                    "target_status_source": "validator",
                    "target_error_type": "validator_error",
                    "target_error_message": str(exc)[:1000],
                    "target_checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "target_response_time_ms": None,
                    "target_redirect_count": 0,
                }
            for link in unresolved[target_url]:
                link.update(result)

            status = _status_code(result.get("target_status"))
            source = result.get("target_status_source")
            if source == "skipped":
                skipped_targets.add(target_url)
                summary["skipped_targets"] = len(skipped_targets)
            else:
                summary["validated_targets"] += 1
                if status == 0:
                    summary["unreachable_targets"] += 1
                elif status is not None and status >= 400:
                    summary["broken_targets"] += 1
                elif status is not None:
                    summary["ok_targets"] += 1

    summary["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
    return summary
