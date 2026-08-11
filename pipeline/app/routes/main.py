import csv
import io
import json
import os
from datetime import date

from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from markupsafe import Markup
import markdown
from sqlalchemy import or_

from app.models import (
    BacklinkHistory,
    Client,
    Competitor,
    CompetitorInsight,
    CrawlIssue,
    CrawlPage,
    CrawlPageImage,
    CrawlPageLink,
    CrawlPageStructuredData,
    Ga4Metric,
    GscMetric,
    Keyword,
    Ranking,
    Snapshot,
    OnePageAudit,
    db,
)
from services.ai_settings import get_effective_ai_settings
from services.health import compute_health_score
from services.make_pdf import markdown_file_to_pdf_bytes
from services.pipeline_runner import enqueue_snapshot_job
from services.one_page_runner import enqueue_one_page_audit

main_bp = Blueprint('main', __name__)


ISSUE_TYPE_PRIORITY = {
    "error": 0,
    "critical": 0,
    "warning": 1,
    "warn": 1,
    "info": 2,
    "notice": 2,
}

GA4_DIMENSION_LABELS = {
    "channel": "Channel",
    "page_path": "Page Path",
    "country": "Country",
    "device": "Device",
}

GA4_SORT_LABELS = {
    "totalUsers": "Total Users",
    "sessions": "Sessions",
    "averageSessionDuration": "Average Session Duration",
    "eventCount": "Event Count",
    "engagementRate": "Engagement Rate",
}

GA4_REPORT_METRICS = [
    "totalUsers",
    "sessions",
    "averageSessionDuration",
    "eventCount",
    "engagementRate",
]

GSC_VIEW_LABELS = {
    "queries": "Queries",
    "urls": "URLs",
    "country": "Country",
    "device": "Device",
}

GSC_SORT_LABELS = {
    "clicks": "Clicks",
    "impressions": "Impressions",
    "ctr": "CTR",
    "position": "Average Position",
}

LINK_SORT_LABELS = {
    "unique_internal_links": "Unique Internal Links",
    "total_internal_links": "Total Internal Links",
}

ISSUE_CATEGORY_DEFINITIONS = [
    {"slug": "meta-titles", "title": "1. Meta Titles", "summary": "Missing, Duplicate, Over 100 Characters, Below 30 Characters, Outside <head>"},
    {"slug": "meta-descriptions", "title": "2. Meta Descriptions", "summary": "Missing, Duplicate, Over 200 Characters, Below 70 Characters"},
    {"slug": "headings", "title": "3. Headings (H1/H2)", "summary": "H1 Missing, H1 Duplicate, Multiple H1s, H2 Duplicate"},
    {"slug": "content", "title": "4. Content", "summary": "Low Word Count Pages, Duplicate Content / Near-Duplicate Pages"},
    {"slug": "canonical-tags", "title": "5. Canonical Tags", "summary": "Missing Canonical Tags, Canonical Pointing to Non-200 URLs"},
    {"slug": "images", "title": "6. Images", "summary": "Image Alt Text Missing, Images Over 100 KB / Uncompressed"},
    {"slug": "internal-linking", "title": "7. Internal Linking", "summary": "Unique In-links, Orphan Pages, Deep Pages"},
    {"slug": "structured-data", "title": "8. Structured Data", "summary": "Schema Validation Errors"},
    {"slug": "redirects", "title": "9. Redirects", "summary": "Redirect Chains, Redirect Loops"},
    {"slug": "sitemaps", "title": "10. Sitemaps", "summary": "URLs Not in Sitemap, Non-200 URLs in Sitemap"},
    {"slug": "errors", "title": "11. Errors", "summary": "4XX Errors, 5XX Errors, Soft 404s"},
    {"slug": "urls", "title": "12. URLs", "summary": "HTTP URLs, Very Long URLs, URLs with Underscores or Mixed Case"},
    {"slug": "indexation", "title": "13. Indexation", "summary": "Noindex Pages, Pages Blocked by robots.txt"},
    {"slug": "page-speed", "title": "14. Page Speed", "summary": "Mobile Page Speed"},
    {"slug": "pages-not-in-sitemap", "title": "15. Pages are not in sitemap.xml", "summary": "Pages that are not included in sitemap.xml"},
    {"slug": "other-technical-issues", "title": "16. Other Technical Issues", "summary": "Issues that do not fit into the above categories"},
]

ISSUE_CATEGORY_ORDER = {item["slug"]: index for index, item in enumerate(ISSUE_CATEGORY_DEFINITIONS)}
ISSUE_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _ranking_lookup_key(keyword_text, location, device):
    return (
        (keyword_text or "").strip().lower(),
        (location or "").strip().lower(),
        (device or "").strip().lower(),
    )


def _build_keyword_rankings(keywords, current_snapshot, previous_snapshot):
    if not current_snapshot:
        return {}

    current_rows = Ranking.query.filter_by(snapshot_id=current_snapshot.id, competitor_id=None).all()
    previous_rows = Ranking.query.filter_by(snapshot_id=previous_snapshot.id, competitor_id=None).all() if previous_snapshot else []

    current_by_keyword = {
        _ranking_lookup_key(row.keyword, row.location, row.device): row for row in current_rows
    }
    previous_by_keyword = {
        _ranking_lookup_key(row.keyword, row.location, row.device): row for row in previous_rows
    }

    keyword_rankings = {}
    for keyword in keywords:
        ranking_key = _ranking_lookup_key(keyword.keyword, keyword.location, keyword.device)
        latest = current_by_keyword.get(ranking_key)
        previous = previous_by_keyword.get(ranking_key)

        current_position = latest.position if latest else None
        previous_position = previous.position if previous else None

        movement = None
        movement_label = "No data"
        movement_tone = "neutral"

        if current_position is not None and previous_position is not None:
            movement = previous_position - current_position
            if movement > 0:
                movement_label = f"Up {movement}"
                movement_tone = "up"
            elif movement < 0:
                movement_label = f"Down {abs(movement)}"
                movement_tone = "down"
            else:
                movement_label = "No change"
        elif current_position is not None:
            movement_label = "New"
            movement_tone = "new"
        elif previous_position is not None:
            movement_label = "Lost"
            movement_tone = "lost"

        keyword_rankings[keyword.id] = {
            "latest": latest,
            "previous": previous,
            "current_position": current_position,
            "previous_position": previous_position,
            "movement": movement,
            "movement_label": movement_label,
            "movement_tone": movement_tone,
        }

    return keyword_rankings


def _compute_keyword_page_score(ranking_row, crawl_pages_by_url):
    if not ranking_row or not ranking_row.url:
        return None

    page = crawl_pages_by_url.get((ranking_row.url or "").strip())
    if not page:
        return None

    score = 100

    if page.status_code and page.status_code >= 400:
        score -= 45
    elif page.status_code and page.status_code >= 300:
        score -= 15

    if not _clean_text(page.title):
        score -= 12
    elif len(_clean_text(page.title)) > 60:
        score -= 4

    if not _clean_text(page.meta_description):
        score -= 10
    elif len(_clean_text(page.meta_description)) > 160:
        score -= 4

    if not _clean_text(page.h1):
        score -= 8

    if not _clean_text(page.canonical_url):
        score -= 8
    elif _clean_text(page.canonical_url) != _clean_text(page.url):
        score -= 6

    if page.word_count is None:
        score -= 6
    elif page.word_count < 200:
        score -= 16
    elif page.word_count < 500:
        score -= 8

    if page.internal_links is not None and page.internal_links <= 1:
        score -= 5

    return max(0, min(100, int(round(score))))


def _group_crawl_issues(crawl_issues):
    grouped = {}
    for row in crawl_issues:
        issue_name = (row.issue or "Unknown issue").strip() or "Unknown issue"
        issue_type = (row.issue_type or "info").strip().lower() or "info"
        bucket = grouped.setdefault(
            issue_name,
            {
                "issue": issue_name,
                "issue_type": issue_type,
                "count": 0,
                "rows": [],
            },
        )
        bucket["count"] += 1
        bucket["rows"].append(row)

        current_priority = ISSUE_TYPE_PRIORITY.get(bucket["issue_type"], 99)
        row_priority = ISSUE_TYPE_PRIORITY.get(issue_type, 99)
        if row_priority < current_priority:
            bucket["issue_type"] = issue_type

    return sorted(
        grouped.values(),
        key=lambda item: (
            ISSUE_TYPE_PRIORITY.get(item["issue_type"], 99),
            -item["count"],
            item["issue"].lower(),
        ),
    )


def _serialize_issue_groups(issue_groups):
    serialized = []
    for group in issue_groups:
        serialized.append({
            "issue": group["issue"],
            "issue_type": group["issue_type"],
            "count": group["count"],
            "rows": [
                {
                    "url": row.url or "",
                    "issue_type": row.issue_type or "",
                    "details": row.details or "",
                }
                for row in group["rows"]
            ],
        })
    return serialized


def _slugify_issue_key(value):
    text = (value or "").strip().lower()
    slug = []
    previous_separator = False
    for char in text:
        if char.isalnum():
            slug.append(char)
            previous_separator = False
        elif not previous_separator:
            slug.append("_")
            previous_separator = True
    return "".join(slug).strip("_") or "issue"


def _normalize_issue_severity(value):
    severity = (value or "").strip().lower()
    if severity in {"critical", "error"}:
        return "high"
    if severity in {"warn", "warning"}:
        return "medium"
    if severity in {"notice", "info"}:
        return "low"
    if severity in ISSUE_SEVERITY_ORDER:
        return severity
    return "medium"


def _issue_row(url, details="", issue_type="", extra=None):
    payload = {
        "url": url or "",
        "details": details or "",
        "issue_type": issue_type or "",
    }
    if extra:
        payload.update(extra)
    return payload


def _issue_category_lookup():
    lookup = {}
    for definition in ISSUE_CATEGORY_DEFINITIONS:
        lookup[definition["slug"]] = {
            "slug": definition["slug"],
            "title": definition["title"],
            "summary": definition["summary"],
            "items": [],
            "total_urls": 0,
            "_seen": set(),
            "_items_by_key": {},
        }
    return lookup


def _push_issue_item(category_lookup, category_slug, key, label, severity, rows):
    category = category_lookup[category_slug]
    item = category["_items_by_key"].get(key)
    if item is None:
        item = {
            "key": key,
            "label": label,
            "severity": severity,
            "count": 0,
            "rows": [],
            "_seen": set(),
        }
        category["_items_by_key"][key] = item
        category["items"].append(item)

    for row in rows:
        if key.startswith("image_"):
            row_key = (
                row.get("url", ""),
                row.get("image_url", ""),
                row.get("position"),
            )
        else:
            row_key = (row.get("url", ""),)
        if row_key in item["_seen"]:
            continue
        item["_seen"].add(row_key)
        item["rows"].append(row)

    item["count"] = len(item["rows"])
    current_priority = ISSUE_SEVERITY_ORDER.get(item["severity"], 99)
    incoming_priority = ISSUE_SEVERITY_ORDER.get(severity, 99)
    if incoming_priority < current_priority:
        item["severity"] = severity


def _meta_length(value):
    return len((value or "").strip())


def _looks_like_duplicate_text_map(values):
    grouped = {}
    for url, text in values:
        normalized = (text or "").strip()
        if not normalized:
            continue
        grouped.setdefault(normalized.lower(), []).append((url, normalized))
    return [items for items in grouped.values() if len(items) > 1]


def _canonical_issue_key(category_slug, issue_text):
    """Map imported issue labels onto the canonical audit row keys."""
    text = (issue_text or "").strip().lower()
    if category_slug == "meta-titles":
        if "missing" in text:
            return "meta_title_missing"
        if "duplicate" in text:
            return "meta_title_duplicate"
        if "100" in text or "long" in text or "over" in text:
            return "meta_title_over_100"
        if "30" in text or "short" in text or "below" in text:
            return "meta_title_below_30"
        if "outside" in text or "head" in text:
            return "meta_title_outside_head"
    elif category_slug == "meta-descriptions":
        if "missing" in text:
            return "meta_description_missing"
        if "duplicate" in text:
            return "meta_description_duplicate"
        if "200" in text or "long" in text or "over" in text:
            return "meta_description_over_200"
        if "70" in text or "short" in text or "below" in text:
            return "meta_description_below_70"
    elif category_slug == "headings":
        if "multiple" in text or "more than one" in text:
            return "multiple_h1s"
        if "h1" in text and "missing" in text:
            return "h1_missing"
        if "h1" in text and "duplicate" in text:
            return "h1_duplicate"
        if "h2" in text and "duplicate" in text:
            return "h2_duplicate"
    elif category_slug == "content":
        if "duplicate" in text or "near-duplicate" in text:
            return "duplicate_content"
        if "word" in text or "thin" in text:
            return "low_word_count"
    elif category_slug == "canonical-tags":
        if "non-200" in text or "status" in text:
            return "canonical_non_200"
        if "missing" in text:
            return "missing_canonical"
    elif category_slug == "images":
        if "alt" in text:
            return "image_alt_missing"
        if "100" in text or "size" in text or "compress" in text:
            return "image_over_100kb"
    elif category_slug == "internal-linking":
        if "orphan" in text:
            return "orphan_pages"
        if "deep" in text or "click" in text:
            return "deep_pages"
    elif category_slug == "errors":
        if "soft" in text:
            return "soft_404s"
        if "5xx" in text or "500" in text:
            return "5xx_errors"
        if "4xx" in text or "404" in text:
            return "4xx_errors"
    elif category_slug == "urls":
        if "http" in text or "https" in text:
            return "http_urls"
    elif category_slug == "indexation":
        if "noindex" in text:
            return "noindex_pages"
        if "robot" in text or "blocked" in text:
            return "robots_blocked_pages"
    return _slugify_issue_key(issue_text or category_slug)


def _categorize_raw_issue(row):
    issue_text = ((row.issue or "") + " " + (row.details or "")).lower()
    if "meta title" in issue_text:
        return "meta-titles"
    if "meta description" in issue_text:
        return "meta-descriptions"
    if "h1" in issue_text or "h2" in issue_text or "heading" in issue_text:
        return "headings"
    if "canonical" in issue_text:
        return "canonical-tags"
    if "alt text" in issue_text or "image" in issue_text:
        return "images"
    if "schema" in issue_text or "structured data" in issue_text or "json-ld" in issue_text:
        return "structured-data"
    if "redirect" in issue_text:
        return "redirects"
    if "sitemap" in issue_text:
        if "not in sitemap" in issue_text:
            return "pages-not-in-sitemap"
        return "sitemaps"
    if "4xx" in issue_text or "5xx" in issue_text or "soft 404" in issue_text:
        return "errors"
    if "robots" in issue_text or "noindex" in issue_text:
        return "indexation"
    if "page speed" in issue_text or "pagespeed" in issue_text:
        return "page-speed"
    if "word count" in issue_text or "thin content" in issue_text or "duplicate content" in issue_text:
        return "content"
    if "url" in issue_text or "https" in issue_text:
        return "urls"
    if "link" in issue_text or "orphan" in issue_text or "deep page" in issue_text:
        return "internal-linking"
    return "other-technical-issues"


def _build_issue_category_groups(crawl_pages, crawl_links, crawl_images, crawl_structured_data, crawl_issues):
    crawl_pages = _dedupe_crawl_pages(crawl_pages)
    crawl_images = _dedupe_crawl_images(crawl_images)
    categories = _issue_category_lookup()
    page_by_url = {(_clean_text(page.url)): page for page in crawl_pages if _clean_text(page.url)}
    inbound_links = {}
    for link in crawl_links:
        if not link.is_internal:
            continue
        target = _clean_text(link.target_url)
        source = _clean_text(link.source_url)
        if not target:
            continue
        inbound_links.setdefault(target, set())
        if source:
            inbound_links[target].add(source)

    missing_title_rows = []
    long_title_rows = []
    short_title_rows = []
    title_outside_head_rows = []
    title_candidates = []
    missing_meta_rows = []
    long_meta_rows = []
    short_meta_rows = []
    meta_candidates = []
    missing_h1_rows = []
    h1_candidates = []
    duplicate_h2_rows = []
    thin_content_rows = []
    missing_canonical_rows = []
    canonical_non_200_rows = []
    http_rows = []
    long_url_rows = []
    underscore_case_rows = []
    noindex_rows = []
    robots_rows = []
    deep_page_rows = []
    orphan_rows = []
    error_4xx_rows = []
    error_5xx_rows = []
    page_speed_rows = []

    for page in crawl_pages:
        url = _clean_text(page.url)
        title = _clean_text(page.title)
        meta_description = _clean_text(page.meta_description)
        h1 = _clean_text(page.h1)
        canonical_url = _clean_text(page.canonical_url)
        robots = _clean_text(page.robots).lower()

        if not title:
            missing_title_rows.append(_issue_row(url, "Missing meta title", "error"))
        else:
            title_candidates.append((url, title))
            if _meta_length(title) > 100:
                long_title_rows.append(_issue_row(url, f"Title length: {_meta_length(title)}", "warning"))
            if _meta_length(title) < 30:
                short_title_rows.append(_issue_row(url, f"Title length: {_meta_length(title)}", "warning"))

        if page.meta_tags and isinstance(page.meta_tags, dict):
            title_found = False
            for tag_name in page.meta_tags.keys():
                if "title" in str(tag_name).lower():
                    title_found = True
                    break
            if title and not title_found:
                title_outside_head_rows.append(_issue_row(url, "Title not found inside parsed head metadata", "error"))

        if not meta_description:
            missing_meta_rows.append(_issue_row(url, "Missing meta description", "error"))
        else:
            meta_candidates.append((url, meta_description))
            if _meta_length(meta_description) > 200:
                long_meta_rows.append(_issue_row(url, f"Meta description length: {_meta_length(meta_description)}", "info"))
            if _meta_length(meta_description) < 70:
                short_meta_rows.append(_issue_row(url, f"Meta description length: {_meta_length(meta_description)}", "info"))

        if not h1:
            missing_h1_rows.append(_issue_row(url, "Missing H1", "error"))
        else:
            h1_candidates.append((url, h1))

        if page.h2 and isinstance(page.h2, list):
            normalized_h2 = [(_clean_text(item).lower()) for item in page.h2 if _clean_text(item)]
            if len(normalized_h2) != len(set(normalized_h2)):
                duplicate_h2_rows.append(_issue_row(url, "Duplicate H2 values detected", "warning"))

        if page.word_count is not None and page.word_count < 200:
            thin_content_rows.append(_issue_row(url, f"Word count: {page.word_count}", "warning"))

        if not canonical_url:
            missing_canonical_rows.append(_issue_row(url, "Missing canonical tag", "error"))
        else:
            canonical_target = page_by_url.get(canonical_url)
            if canonical_target and canonical_target.status_code and canonical_target.status_code >= 300:
                canonical_non_200_rows.append(_issue_row(url, f"Canonical target status: {canonical_target.status_code}", "error"))

        if url.startswith("http://"):
            http_rows.append(_issue_row(url, "URL is not HTTPS", "error"))
        if len(url) > 115:
            long_url_rows.append(_issue_row(url, f"URL length: {len(url)}", "info"))
        path_part = url.split("://", 1)[-1]
        if "_" in path_part or any(char.isalpha() and char != char.lower() for char in path_part):
            underscore_case_rows.append(_issue_row(url, "URL contains underscores or mixed case", "info"))

        if "noindex" in robots:
            noindex_rows.append(_issue_row(url, f"Robots: {robots}", "warning"))
        if "disallow" in robots or "blocked" in robots:
            robots_rows.append(_issue_row(url, f"Robots: {robots}", "error"))

        if page.depth is not None and page.depth > 3:
            deep_page_rows.append(_issue_row(url, f"Depth: {page.depth}", "warning"))
        if page.is_internal and not inbound_links.get(url):
            orphan_rows.append(_issue_row(url, "No internal source URLs found", "error"))

        if page.status_code is not None and 400 <= page.status_code < 500:
            error_4xx_rows.append(_issue_row(url, f"HTTP status: {page.status_code}", "error"))
            if page.status_code == 404 and page.error_type and "soft" in page.error_type.lower():
                pass
        if page.status_code is not None and page.status_code >= 500:
            error_5xx_rows.append(_issue_row(url, f"HTTP status: {page.status_code}", "error"))

        if page.response_time is not None and page.response_time > 2.5:
            page_speed_rows.append(_issue_row(url, f"Response time: {page.response_time:.2f}s", "warning"))

    duplicate_title_rows = []
    for items in _looks_like_duplicate_text_map(title_candidates):
        for url, normalized in items:
            duplicate_title_rows.append(_issue_row(url, f"Duplicate title: {normalized[:120]}", "error"))

    duplicate_meta_rows = []
    for items in _looks_like_duplicate_text_map(meta_candidates):
        for url, normalized in items:
            duplicate_meta_rows.append(_issue_row(url, f"Duplicate meta description: {normalized[:140]}", "warning"))

    duplicate_h1_rows = []
    for items in _looks_like_duplicate_text_map(h1_candidates):
        for url, normalized in items:
            duplicate_h1_rows.append(_issue_row(url, f"Duplicate H1: {normalized[:120]}", "warning"))

    multiple_h1_rows = []
    for page in crawl_pages:
        h1_values = page.h1 if isinstance(page.h1, list) else []
        if len([value for value in h1_values if _clean_text(value)]) > 1:
            multiple_h1_rows.append(_issue_row(page.url, "Multiple H1 values detected", "warning"))

    missing_alt_rows = []
    oversized_image_rows = []
    for image in crawl_images:
        if not _clean_text(image.alt_text):
            missing_alt_rows.append(_issue_row(
                image.page_url,
                "Missing alt text",
                "warning",
                {"image_url": image.image_url or "", "position": image.position},
            ))
        if image.file_size_bytes and image.file_size_bytes > 102400:
            oversized_image_rows.append(_issue_row(
                image.page_url,
                f"Image size: {round(image.file_size_bytes / 1024, 1)} KB",
                "warning",
                {"image_url": image.image_url or "", "position": image.position},
            ))

    schema_issue_rows = []
    for row in crawl_structured_data:
        payload = row.payload or {}
        if isinstance(payload, dict) and payload.get("errors"):
            schema_issue_rows.append(_issue_row(
                row.page_url,
                f"Schema validation errors in {row.schema_type or row.source}",
                "warning",
            ))

    broken_link_rows = []
    for link in crawl_links:
        if link.target_status is not None and link.target_status >= 400:
            broken_link_rows.append(_issue_row(
                link.source_url,
                f"Broken target: {link.target_url or 'N/A'} | Anchor: {link.anchor_text or 'N/A'}",
                "error",
                {"target_url": link.target_url or "", "anchor_text": link.anchor_text or ""},
            ))

    _push_issue_item(categories, "meta-titles", "meta_title_missing", "Meta title missing", "high", missing_title_rows)
    _push_issue_item(categories, "meta-titles", "meta_title_duplicate", "Meta title duplicate", "high", duplicate_title_rows)
    _push_issue_item(categories, "meta-titles", "meta_title_over_100", "Meta title over 100 characters", "medium", long_title_rows)
    _push_issue_item(categories, "meta-titles", "meta_title_below_30", "Meta title below 30 characters", "medium", short_title_rows)
    _push_issue_item(categories, "meta-titles", "meta_title_outside_head", "Meta title outside <head>", "high", title_outside_head_rows)

    _push_issue_item(categories, "meta-descriptions", "meta_description_missing", "Meta description missing", "high", missing_meta_rows)
    _push_issue_item(categories, "meta-descriptions", "meta_description_duplicate", "Meta description duplicate", "medium", duplicate_meta_rows)
    _push_issue_item(categories, "meta-descriptions", "meta_description_over_200", "Meta description over 200 characters", "low", long_meta_rows)
    _push_issue_item(categories, "meta-descriptions", "meta_description_below_70", "Meta description below 70 characters", "low", short_meta_rows)

    _push_issue_item(categories, "headings", "h1_missing", "H1 missing", "high", missing_h1_rows)
    _push_issue_item(categories, "headings", "h1_duplicate", "H1 duplicate", "medium", duplicate_h1_rows)
    _push_issue_item(categories, "headings", "multiple_h1s", "Multiple H1s", "medium", multiple_h1_rows)
    _push_issue_item(categories, "headings", "h2_duplicate", "H2 duplicate", "medium", duplicate_h2_rows)

    _push_issue_item(categories, "content", "low_word_count", "Low word count pages", "medium", thin_content_rows)
    _push_issue_item(categories, "content", "duplicate_content", "Duplicate content / near-duplicate pages", "high", [])

    _push_issue_item(categories, "canonical-tags", "missing_canonical", "Missing canonical tags", "high", missing_canonical_rows)
    _push_issue_item(categories, "canonical-tags", "canonical_non_200", "Canonical pointing to non-200 URLs", "high", canonical_non_200_rows)

    _push_issue_item(categories, "images", "image_alt_missing", "Image alt text missing", "medium", missing_alt_rows)
    _push_issue_item(categories, "images", "image_over_100kb", "Images over 100 KB / uncompressed", "medium", oversized_image_rows)

    _push_issue_item(categories, "internal-linking", "broken_links", "Broken links", "high", broken_link_rows)
    _push_issue_item(categories, "internal-linking", "orphan_pages", "Orphan pages", "high", orphan_rows)
    _push_issue_item(categories, "internal-linking", "deep_pages", "Deep pages (more than 3-4 clicks from homepage)", "medium", deep_page_rows)

    _push_issue_item(categories, "structured-data", "schema_validation_errors", "Schema validation errors", "medium", schema_issue_rows)

    _push_issue_item(categories, "errors", "4xx_errors", "4XX errors", "high", error_4xx_rows)
    _push_issue_item(categories, "errors", "5xx_errors", "5XX errors", "high", error_5xx_rows)

    _push_issue_item(categories, "urls", "http_urls", "HTTP URLs (non-HTTPS)", "high", http_rows)
    _push_issue_item(categories, "urls", "very_long_urls", "Very long URLs (over 115 characters)", "low", long_url_rows)
    _push_issue_item(categories, "urls", "underscores_or_mixed_case", "URLs with underscores or mixed case", "low", underscore_case_rows)

    _push_issue_item(categories, "indexation", "noindex_pages", "Noindex pages", "medium", noindex_rows)
    _push_issue_item(categories, "indexation", "robots_blocked_pages", "Pages blocked by robots.txt", "high", robots_rows)

    _push_issue_item(categories, "page-speed", "mobile_page_speed", "Mobile Page Speed", "medium", page_speed_rows)

    for row in crawl_issues:
        category_slug = _categorize_raw_issue(row)
        raw_issue_text = ((row.issue or "") + " " + (row.details or "")).lower()
        if category_slug == "images" and "alt" in raw_issue_text:
            # Missing-alt findings are derived from CrawlPageImage below.
            # Do not add the page-level CrawlIssue representation a second time.
            continue
        issue_key = _canonical_issue_key(category_slug, row.issue or row.details or category_slug)
        severity = _normalize_issue_severity(row.issue_type)
        _push_issue_item(
            categories,
            category_slug,
            issue_key,
            (row.issue or "Technical issue").strip() or "Technical issue",
            severity,
            [_issue_row(row.url, row.details or "", row.issue_type or "")],
        )

    result = []
    for definition in ISSUE_CATEGORY_DEFINITIONS:
        category = categories[definition["slug"]]
        category["items"].sort(
            key=lambda item: (
                ISSUE_SEVERITY_ORDER.get(item["severity"], 99),
                -item["count"],
                item["label"].lower(),
            )
        )
        category["total_urls"] = len({
            row.get("url", "")
            for item in category["items"]
            for row in item["rows"]
            if row.get("url", "")
        })
        result.append({
            "slug": category["slug"],
            "title": category["title"],
            "summary": category["summary"],
            "total_urls": category["total_urls"],
            "items": [
                {
                    "key": item["key"],
                    "label": item["label"],
                    "severity": item["severity"],
                    "count": item["count"],
                    "rows": item["rows"],
                }
                for item in category["items"]
            ],
        })
    return result


def _serialize_issue_category_groups(issue_category_groups):
    serialized = []
    for category in issue_category_groups:
        serialized.append({
            "slug": category["slug"],
            "title": category["title"],
            "summary": category["summary"],
            "total_urls": category["total_urls"],
            "items": category["items"],
        })
    return serialized


def _clean_text(value):
    return (value or "").strip()


def _report_markdown_path(client, snapshot):
    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.md"
    return os.path.join('reports', filename)


def _safe_date_text(value):
    try:
        return date.fromisoformat(value).isoformat() if value else ""
    except ValueError:
        return ""


def _parse_prefixed_value(value, fallback_type):
    text = (value or "").strip()
    if not text:
        return fallback_type, ""
    if "::" not in text:
        return fallback_type, text
    prefix, actual = text.split("::", 1)
    return prefix.strip().lower(), actual.strip()


def _ga4_dimension_parts(row):
    dimension_type, dimension_value = _parse_prefixed_value(row.dimension, "channel")
    return dimension_type, dimension_value or "N/A"


def _gsc_view_parts(row):
    if row.page:
        view_type, view_value = _parse_prefixed_value(row.page, "page")
    else:
        view_type, view_value = _parse_prefixed_value(row.query, "query")

    normalized = {
        "query": "queries",
        "page": "urls",
        "country": "country",
        "device": "device",
    }.get(view_type, "queries")
    return normalized, view_value or "N/A"


def _selected_date_range(default_rows, prefix):
    starts = sorted({_safe_date_text(row.period_start) for row in default_rows if _safe_date_text(row.period_start)})
    ends = sorted({_safe_date_text(row.period_end) for row in default_rows if _safe_date_text(row.period_end)})
    default_start = starts[0] if starts else ""
    default_end = ends[-1] if ends else ""
    selected_start = _safe_date_text(request.args.get(f"{prefix}_start")) or default_start
    selected_end = _safe_date_text(request.args.get(f"{prefix}_end")) or default_end
    return {
        "default_start": default_start,
        "default_end": default_end,
        "selected_start": selected_start,
        "selected_end": selected_end,
    }


def _matches_selected_range(row, selected_start, selected_end):
    row_start = _safe_date_text(row.period_start)
    row_end = _safe_date_text(row.period_end)
    if selected_start and row_start and row_start < selected_start:
        return False
    if selected_end and row_end and row_end > selected_end:
        return False
    return True


def _build_ga4_report(ga4_metrics):
    date_range = _selected_date_range(ga4_metrics, "ga4")
    selected_dimension = request.args.get("ga4_dimension", "channel").strip().lower()
    if selected_dimension not in GA4_DIMENSION_LABELS:
        selected_dimension = "channel"

    selected_sort = request.args.get("ga4_sort", "sessions").strip()
    if selected_sort not in GA4_SORT_LABELS:
        selected_sort = "sessions"

    selected_order = request.args.get("ga4_order", "desc").strip().lower()
    if selected_order not in {"asc", "desc"}:
        selected_order = "desc"

    grouped_rows = {}
    for row in ga4_metrics:
        dimension_type, dimension_value = _ga4_dimension_parts(row)
        if dimension_type != selected_dimension:
            continue
        if not _matches_selected_range(row, date_range["selected_start"], date_range["selected_end"]):
            continue
        bucket = grouped_rows.setdefault(
            dimension_value,
            {
                "dimension_type": dimension_type,
                "dimension_value": dimension_value,
                "metrics": {metric: None for metric in GA4_REPORT_METRICS},
            },
        )
        if row.metric_name in GA4_REPORT_METRICS:
            bucket["metrics"][row.metric_name] = row.metric_value

    filtered_rows = list(grouped_rows.values())
    reverse = selected_order == "desc"
    missing_rank = 999999999 if selected_order == "asc" else -1
    filtered_rows.sort(
        key=lambda item: (
            item["metrics"][selected_sort] if item["metrics"][selected_sort] is not None else missing_rank,
            item["dimension_value"].lower(),
        ),
        reverse=reverse,
    )

    return {
        "rows": filtered_rows,
        "selected_dimension": selected_dimension,
        "selected_sort": selected_sort,
        "selected_order": selected_order,
        "dimension_label": GA4_DIMENSION_LABELS[selected_dimension],
        "date_range": date_range,
        "metric_labels": {metric: GA4_SORT_LABELS[metric] for metric in GA4_REPORT_METRICS},
    }


def _build_gsc_report(gsc_metrics):
    date_range = _selected_date_range(gsc_metrics, "gsc")
    selected_view = request.args.get("gsc_view", "queries").strip().lower()
    if selected_view not in GSC_VIEW_LABELS:
        selected_view = "queries"

    selected_sort = request.args.get("gsc_sort", "impressions").strip()
    if selected_sort not in GSC_SORT_LABELS:
        selected_sort = "impressions"
    selected_order = request.args.get("gsc_order", "desc").strip().lower()
    if selected_order not in {"asc", "desc"}:
        selected_order = "desc"

    filtered_rows = []
    for row in gsc_metrics:
        view_type, view_value = _gsc_view_parts(row)
        if view_type != selected_view:
            continue
        if not _matches_selected_range(row, date_range["selected_start"], date_range["selected_end"]):
            continue
        filtered_rows.append({
            "label": view_value,
                "clicks": row.clicks or 0,
                "impressions": row.impressions or 0,
                "ctr": row.ctr or 0,
                "position": row.position,
            })

    if selected_sort == "position":
        reverse = selected_order == "desc"
        missing_rank = -1 if reverse else 999999
        filtered_rows.sort(
            key=lambda item: (
                item["position"] if item["position"] is not None else missing_rank,
                item["label"].lower(),
            ),
            reverse=reverse,
        )
        if selected_order == "asc":
            filtered_rows.sort(
                key=lambda item: (
                    item["position"] is None,
                    item["position"] if item["position"] is not None else 999999,
                    item["label"].lower(),
                )
            )
        else:
            filtered_rows.sort(
                key=lambda item: (
                    item["position"] is not None,
                    item["position"] if item["position"] is not None else -1,
                    item["label"].lower(),
                ),
                reverse=True,
            )
    else:
        reverse = selected_order == "desc"
        missing_rank = -1 if reverse else 999999999
        filtered_rows.sort(
            key=lambda item: (
                item[selected_sort] if item[selected_sort] is not None else missing_rank,
                item["label"].lower(),
            ),
            reverse=reverse,
        )

    return {
        "rows": filtered_rows,
        "selected_view": selected_view,
        "selected_sort": selected_sort,
        "selected_order": selected_order,
        "view_label": GSC_VIEW_LABELS[selected_view],
        "date_range": date_range,
    }


def _meta_length(value):
    return len(_clean_text(value))


def _build_broken_link_report(crawl_links, limit=150):
    rows = []
    for row in crawl_links:
        if row.target_status is None or row.target_status < 400:
            continue
        rows.append({
            "broken_url": row.target_url or "",
            "anchor_text": row.anchor_text or "",
            "source_url": row.source_url or "",
            "status_code": row.target_status,
            "link_scope": "Internal" if row.is_internal else "External",
        })

    rows.sort(key=lambda item: (-int(item["status_code"] or 0), item["source_url"], item["broken_url"]))
    return {
        "total": len(rows),
        "rows": rows[:limit],
    }


def _build_internal_link_report(crawl_pages, crawl_links, limit=150, sort_key="unique_internal_links", sort_order="desc"):
    crawl_pages = _dedupe_crawl_pages(crawl_pages)
    inbound_unique = {}
    inbound_total = {}

    for row in crawl_links:
        if not row.is_internal or not row.target_url:
            continue
        inbound_total[row.target_url] = inbound_total.get(row.target_url, 0) + 1
        inbound_unique.setdefault(row.target_url, set()).add(row.source_url or "")

    rows = []
    for page in crawl_pages:
        if page.is_internal is False:
            continue
        unique_sources = inbound_unique.get(page.url, set())
        rows.append({
            "url": page.url,
            "title": page.title or "",
            "status_code": page.status_code,
            "unique_internal_links": len([value for value in unique_sources if value]),
            "total_internal_links": inbound_total.get(page.url, 0),
            "word_count": page.word_count,
        })

    selected_sort = sort_key if sort_key in LINK_SORT_LABELS else "unique_internal_links"
    selected_order = sort_order if sort_order in {"asc", "desc"} else "desc"
    reverse = selected_order == "desc"

    if selected_sort == "url":
        rows.sort(key=lambda item: item["url"], reverse=reverse)
    elif selected_sort == "status_code":
        missing_rank = -1 if reverse else 999999
        rows.sort(
            key=lambda item: (
                item["status_code"] if item["status_code"] is not None else missing_rank,
                item["url"],
            ),
            reverse=reverse,
        )
    else:
        rows.sort(
            key=lambda item: (
                item[selected_sort],
                item["unique_internal_links"] if selected_sort != "unique_internal_links" else item["total_internal_links"],
                item["url"],
            ),
            reverse=reverse,
        )

    return {
        "total": len(rows),
        "rows": rows[:limit],
        "selected_sort": selected_sort,
        "selected_order": selected_order,
    }


def _build_image_report(crawl_images, limit=150):
    crawl_images = _dedupe_crawl_images(crawl_images)
    rows = []
    missing_alt = 0
    for row in crawl_images:
        alt_text = _clean_text(row.alt_text)
        missing = not alt_text
        if missing:
            missing_alt += 1
        rows.append({
            "image_url": row.image_url or "",
            "page_url": row.page_url or "",
            "alt_text": alt_text,
            "file_size_bytes": row.file_size_bytes,
            "dimensions": "×".join(str(value) for value in (row.width, row.height) if value) or "N/A",
            "alt_state": "Missing" if missing else "Present",
        })

    rows.sort(key=lambda item: (item["alt_state"] != "Missing", item["page_url"], item["image_url"]))
    return {
        "total": len(rows),
        "missing_alt": missing_alt,
        "page_count": len({row["page_url"] for row in rows if row["page_url"]}),
        "unique_assets": len({row["image_url"] for row in rows if row["image_url"]}),
        "rows": rows[:limit],
    }


def _dedupe_crawl_pages(crawl_pages):
    """Keep one page record per URL for page-level reports and issue checks."""
    unique_pages = []
    seen_urls = set()
    for page in crawl_pages:
        page_url = _clean_text(page.url)
        if not page_url or page_url in seen_urls:
            continue
        seen_urls.add(page_url)
        unique_pages.append(page)
    return unique_pages


def _dedupe_crawl_images(crawl_images):
    """Remove duplicate image occurrences created by duplicate crawl pages."""
    unique_rows = []
    seen = set()
    for row in crawl_images:
        key = (
            _clean_text(row.page_url),
            _clean_text(row.image_url),
            row.position,
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def _build_meta_tag_report(crawl_pages, limit=150):
    crawl_pages = _dedupe_crawl_pages(crawl_pages)
    title_counts = {}
    meta_counts = {}
    for page in crawl_pages:
        title = _clean_text(page.title)
        meta = _clean_text(page.meta_description)
        if title:
            title_counts[title] = title_counts.get(title, 0) + 1
        if meta:
            meta_counts[meta] = meta_counts.get(meta, 0) + 1

    rows = []
    flagged = 0
    for page in crawl_pages:
        title = _clean_text(page.title)
        meta = _clean_text(page.meta_description)
        title_length = len(title)
        meta_length = len(meta)
        flags = []

        if not title:
            flags.append("Missing title")
        elif title_counts.get(title, 0) > 1:
            flags.append("Duplicate title")
        elif title_length > 60:
            flags.append("Long title")

        if not meta:
            flags.append("Missing meta description")
        elif meta_counts.get(meta, 0) > 1:
            flags.append("Duplicate meta description")
        elif meta_length > 160:
            flags.append("Long meta description")

        if flags:
            flagged += 1

        rows.append({
            "url": page.url,
            "title": title,
            "meta_description": meta,
            "title_length": title_length or 0,
            "meta_length": meta_length or 0,
            "word_count": page.word_count,
            "flags": flags,
        })

    rows.sort(key=lambda item: (-len(item["flags"]), item["url"]))
    return {
        "total": len(rows),
        "flagged": flagged,
        "rows": rows[:limit],
    }


def _build_word_count_report(crawl_pages, limit=150):
    crawl_pages = _dedupe_crawl_pages(crawl_pages)
    rows = []
    thin_count = 0
    for page in crawl_pages:
        if page.is_internal is False:
            continue
        word_count = page.word_count
        if word_count is None:
            bucket = "Unknown"
        elif word_count < 200:
            bucket = "Thin"
            thin_count += 1
        elif word_count < 500:
            bucket = "Medium"
        else:
            bucket = "Strong"

        rows.append({
            "url": page.url,
            "title": page.title or "",
            "word_count": word_count,
            "bucket": bucket,
        })

    rows.sort(key=lambda item: (item["word_count"] is None, item["word_count"] if item["word_count"] is not None else 10**9, item["url"]))
    return {
        "total": len(rows),
        "thin_count": thin_count,
        "rows": rows[:limit],
    }


def _build_canonical_report(crawl_pages, limit=150):
    crawl_pages = _dedupe_crawl_pages(crawl_pages)
    rows = []
    for page in crawl_pages:
        canonical_url = _clean_text(page.canonical_url)
        flags = []
        if not canonical_url:
            flags.append("Missing canonical")
        elif canonical_url != page.url:
            flags.append("Canonical points elsewhere")

        if not flags:
            continue

        rows.append({
            "url": page.url,
            "canonical_url": canonical_url,
            "flags": flags,
        })

    rows.sort(key=lambda item: (-len(item["flags"]), item["url"]))
    return {
        "total": len(rows),
        "rows": rows[:limit],
    }


def _csv_response(filename, headers, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@main_bp.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        clients = Client.query.all()
    else:
        # User can only see clients assigned to them
        clients = current_user.clients
        
    return render_template('index.html', clients=clients)


def _user_one_page_audits():
    if current_user.role == 'admin':
        return OnePageAudit.query.order_by(OnePageAudit.created_at.desc()).all()

    client_ids = [client.id for client in current_user.clients]
    filters = [OnePageAudit.created_by_user_id == current_user.id]
    if client_ids:
        filters.append(OnePageAudit.client_id.in_(client_ids))
    return OnePageAudit.query.filter(or_(*filters)).order_by(OnePageAudit.created_at.desc()).all()


@main_bp.route('/one-page-analysis', methods=['GET', 'POST'])
@login_required
def one_page_analysis():
    clients = Client.query.all() if current_user.role == 'admin' else current_user.clients

    if request.method == 'POST':
        url = (request.form.get('url') or '').strip()
        target_keyword = (request.form.get('target_keyword') or '').strip() or None
        client_id = request.form.get('client_id', type=int)

        if not url.startswith(('http://', 'https://')):
            flash('Enter a complete URL starting with http:// or https://.', 'error')
            return render_template('one_page_analysis.html', audits=_user_one_page_audits(), clients=clients, form_url=url, target_keyword=target_keyword)

        client = Client.query.get(client_id) if client_id else None
        if client and current_user.role != 'admin' and client not in current_user.clients:
            abort(403)

        audit = OnePageAudit(
            client_id=client.id if client else None,
            created_by_user_id=current_user.id,
            url=url,
            normalized_url=url.rstrip('/'),
            target_keyword=target_keyword,
            status='pending',
        )
        db.session.add(audit)
        db.session.commit()
        enqueue_one_page_audit(current_app._get_current_object(), audit.id)
        flash('The page audit has been queued and will start analyzing shortly.', 'success')
        return redirect(url_for('main.one_page_audit_detail', audit_id=audit.id))

    return render_template('one_page_analysis.html', audits=_user_one_page_audits(), clients=clients, form_url='', target_keyword='')


@main_bp.route('/one-page-analysis/<int:audit_id>')
@login_required
def one_page_audit_detail(audit_id):
    audit = OnePageAudit.query.get_or_404(audit_id)
    if current_user.role != 'admin':
        allowed_client_ids = {client.id for client in current_user.clients}
        if audit.created_by_user_id != current_user.id and audit.client_id not in allowed_client_ids:
            abort(403)

    return render_template(
        'one_page_audit_detail.html',
        audit=audit,
        findings=sorted(audit.findings, key=lambda item: (item.sort_order or 0, item.id)),
        metrics=sorted(audit.metrics, key=lambda item: item.label.lower()),
    )


@main_bp.route('/one-page-analysis/<int:audit_id>/pdf')
@login_required
def one_page_audit_pdf(audit_id):
    audit = OnePageAudit.query.get_or_404(audit_id)
    if current_user.role != 'admin':
        allowed_client_ids = {client.id for client in current_user.clients}
        if audit.created_by_user_id != current_user.id and audit.client_id not in allowed_client_ids:
            abort(403)

    if not audit.pdf_path or not os.path.exists(audit.pdf_path):
        flash('The PDF will be available after this audit has been completed.', 'info')
        return redirect(url_for('main.one_page_audit_detail', audit_id=audit.id))
    return send_file(audit.pdf_path, as_attachment=True, download_name=f'one_page_audit_{audit.id}.pdf', mimetype='application/pdf')


@main_bp.route('/project/<int:client_id>/competitor/<int:competitor_id>')
@login_required
def competitor_detail(client_id, competitor_id):
    client = Client.query.get_or_404(client_id)
    competitor = Competitor.query.filter_by(id=competitor_id, client_id=client.id).first_or_404()
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    insight = CompetitorInsight.query.filter_by(competitor_id=competitor.id).order_by(CompetitorInsight.created_at.desc()).first()
    return render_template(
        'competitor_detail.html',
        client=client,
        competitor=competitor,
        insight=insight,
        summary=(insight.summary if insight else {}) or {},
        ranked_keywords=(insight.ranked_keywords if insight else []) or [],
        top_pages=(insight.top_pages if insight else []) or [],
    )

@main_bp.route('/project/<int:client_id>')
@login_required
def project(client_id):
    client = Client.query.get_or_404(client_id)
    
    # Check authorization if not admin
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
        
    snapshots = Snapshot.query.filter_by(client_id=client_id).order_by(Snapshot.created_at.desc()).all()
    keywords = Keyword.query.filter_by(client_id=client_id).order_by(Keyword.priority.asc(), Keyword.keyword.asc()).all()

    completed_snapshots = [snapshot for snapshot in snapshots if snapshot.status in ("complete", "partial")]
    latest_snapshot = completed_snapshots[0] if completed_snapshots else None
    previous_snapshot = completed_snapshots[1] if len(completed_snapshots) > 1 else None
    keyword_rankings = _build_keyword_rankings(keywords, latest_snapshot, previous_snapshot)
    health_score = compute_health_score(latest_snapshot, previous_snapshot)
    effective_ai_settings = get_effective_ai_settings(client.id)
    active_tab = request.args.get('tab', 'overview')
    if active_tab not in {"overview", "keywords", "history"}:
        active_tab = "overview"

    parsed_notes = {}
    for snapshot in snapshots:
        try:
            parsed_notes[snapshot.id] = json.loads(snapshot.notes) if snapshot.notes else {}
        except json.JSONDecodeError:
            parsed_notes[snapshot.id] = {"raw": snapshot.notes}

    return render_template(
        'project.html',
        client=client,
        snapshots=snapshots,
        keywords=keywords,
        latest_snapshot=latest_snapshot,
        previous_snapshot=previous_snapshot,
        keyword_rankings=keyword_rankings,
        health_score=health_score,
        effective_ai_settings=effective_ai_settings,
        parsed_notes=parsed_notes,
        active_tab=active_tab,
    )


@main_bp.route('/project/<int:client_id>/keywords/download')
@login_required
def download_keyword_rankings_csv(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    snapshots = Snapshot.query.filter_by(client_id=client_id).order_by(Snapshot.created_at.desc()).all()
    keywords = Keyword.query.filter_by(client_id=client_id).order_by(Keyword.priority.asc(), Keyword.keyword.asc()).all()
    latest_snapshot = next((snapshot for snapshot in snapshots if snapshot.status in ("complete", "partial")), None)

    if not latest_snapshot:
        flash("No completed snapshot is available yet for keyword export.", "error")
        return redirect(url_for('main.project', client_id=client.id))

    keyword_rankings = _build_keyword_rankings(keywords, latest_snapshot, None)
    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=latest_snapshot.id).all()
    crawl_pages_by_url = {_clean_text(page.url): page for page in crawl_pages if _clean_text(page.url)}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sr. No.", "Keyword", "Search Volume", "Page Score", "Ranking URL"])

    for index, keyword in enumerate(keywords, start=1):
        ranking_state = keyword_rankings.get(keyword.id, {})
        latest = ranking_state.get("latest")
        page_score = _compute_keyword_page_score(latest, crawl_pages_by_url)

        writer.writerow([
            index,
            keyword.keyword,
            latest.search_volume if latest and latest.search_volume is not None else "",
            page_score if page_score is not None else "N/A",
            latest.url if latest and latest.url else "N/A",
        ])

    filename = f"{client.name.replace(' ', '_')}_keyword_rankings_snapshot{latest_snapshot.id}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@main_bp.route('/project/<int:client_id>/analyze', methods=['POST'])
@login_required
def analyze(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    snapshot = enqueue_snapshot_job(current_app._get_current_object(), client_id)
    flash(f"Analysis queued for snapshot #{snapshot.id}. Data collection has started in the background.", "success")
    return redirect(url_for('main.project', client_id=client_id))

@main_bp.route('/report/<int:snapshot_id>')
@login_required
def view_report(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get(snapshot.client_id)
    
    # Authorize
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
        
    filepath = _report_markdown_path(client, snapshot)
    
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        report_html = markdown.markdown(
            content,
            extensions=[
                'extra',
                'sane_lists',
                'tables',
                'fenced_code',
                'toc',
            ],
        )
        return render_template(
            'report_view.html',
            client=client,
            snapshot=snapshot,
            report_title=f"{client.name} SEO Report",
            report_html=Markup(report_html),
        )
    else:
        flash("Report file not found. It might still be generating or was deleted.", "error")
        return redirect(url_for('main.project', client_id=client.id, tab='history'))


@main_bp.route('/report/<int:snapshot_id>/download')
@login_required
def download_report(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    pdf_filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}.pdf"
    filepath = _report_markdown_path(client, snapshot)
    if not os.path.exists(filepath):
        flash("Report file not found. It might still be generating or was deleted.", "error")
        return redirect(url_for('main.project', client_id=client.id, tab='history'))

    try:
        pdf_bytes = markdown_file_to_pdf_bytes(filepath)
    except Exception as exc:
        current_app.logger.exception("Failed to render PDF for snapshot %s", snapshot.id)
        flash(f"Could not generate PDF report: {exc}", "error")
        return redirect(url_for('main.project', client_id=client.id))

    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={"Content-Disposition": f'attachment; filename="{pdf_filename}"'},
    )


@main_bp.route('/snapshot/<int:snapshot_id>/delete', methods=['POST'])
@login_required
def delete_snapshot(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    filepath = _report_markdown_path(client, snapshot)

    try:
        db.session.delete(snapshot)
        db.session.commit()

        if os.path.exists(filepath):
            os.remove(filepath)

        flash(f"Snapshot #{snapshot_id} was deleted.", "success")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to delete snapshot %s", snapshot_id)
        flash(f"Could not delete snapshot #{snapshot_id}.", "error")

    return redirect(url_for('main.project', client_id=client.id, tab='history'))


@main_bp.route('/snapshot/<int:snapshot_id>')
@login_required
def snapshot_detail(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_issues = db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot_id).order_by(CrawlIssue.issue_type.asc(), CrawlIssue.issue.asc(), CrawlIssue.url.asc()).all()
    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    crawl_links = db.session.query(CrawlPageLink).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageLink.source_url.asc(), CrawlPageLink.target_url.asc()).all()
    crawl_images = db.session.query(CrawlPageImage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageImage.page_url.asc(), CrawlPageImage.position.asc(), CrawlPageImage.image_url.asc()).all()
    crawl_images = _dedupe_crawl_images(crawl_images)
    crawl_structured_data = db.session.query(CrawlPageStructuredData).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageStructuredData.page_url.asc(), CrawlPageStructuredData.position.asc()).all()
    ga4_metrics = db.session.query(Ga4Metric).filter_by(snapshot_id=snapshot_id).order_by(Ga4Metric.metric_name.asc(), Ga4Metric.metric_value.desc()).all()
    gsc_metrics = db.session.query(GscMetric).filter_by(snapshot_id=snapshot_id).order_by(GscMetric.impressions.desc()).all()
    rankings = db.session.query(Ranking).filter_by(snapshot_id=snapshot_id, competitor_id=None).order_by(Ranking.search_volume.desc().nullslast(), Ranking.keyword.asc()).all()
    competitor_rankings = db.session.query(Ranking).filter(
        Ranking.snapshot_id == snapshot_id,
        Ranking.competitor_id.isnot(None),
    ).join(Competitor, Ranking.competitor_id == Competitor.id).order_by(Competitor.domain.asc(), Ranking.keyword.asc()).all()
    backlinks = db.session.query(BacklinkHistory).filter_by(snapshot_id=snapshot_id, competitor_id=None).all()
    competitor_backlinks = db.session.query(BacklinkHistory).filter(
        BacklinkHistory.snapshot_id == snapshot_id,
        BacklinkHistory.competitor_id.isnot(None),
    ).join(Competitor, BacklinkHistory.competitor_id == Competitor.id).order_by(Competitor.domain.asc()).all()
    issue_category_groups = _build_issue_category_groups(
        crawl_pages,
        crawl_links,
        crawl_images,
        crawl_structured_data,
        crawl_issues,
    )
    issue_groups_data = _serialize_issue_category_groups(issue_category_groups)
    selected_category = issue_category_groups[0] if issue_category_groups else None
    selected_item = selected_category["items"][0] if selected_category and selected_category["items"] else None
    selected_issue_rows = selected_item["rows"] if selected_item else []
    broken_link_report = _build_broken_link_report(crawl_links)
    link_sort = (request.args.get("link_sort") or "unique_internal_links").strip()
    link_order = (request.args.get("link_order") or "desc").strip().lower()
    internal_link_report = _build_internal_link_report(crawl_pages, crawl_links, sort_key=link_sort, sort_order=link_order)
    image_report = _build_image_report(crawl_images)
    meta_tag_report = _build_meta_tag_report(crawl_pages)
    word_count_report = _build_word_count_report(crawl_pages)
    canonical_report = _build_canonical_report(crawl_pages)
    ga4_report = _build_ga4_report(ga4_metrics)
    gsc_report = _build_gsc_report(gsc_metrics)

    try:
        notes = json.loads(snapshot.notes) if snapshot.notes else {}
    except json.JSONDecodeError:
        notes = {"raw": snapshot.notes}

    return render_template(
        'snapshot_detail.html',
        client=client,
        snapshot=snapshot,
        notes=notes,
        crawl_issues=crawl_issues,
        crawl_pages=crawl_pages,
        crawl_links=crawl_links,
        crawl_images=crawl_images,
        issue_groups=issue_category_groups,
        issue_groups_data=issue_groups_data,
        selected_issue=selected_item["key"] if selected_item else "",
        selected_issue_label=selected_item["label"] if selected_item else "",
        selected_issue_category=selected_category["slug"] if selected_category else "",
        selected_issue_rows=selected_issue_rows,
        broken_link_report=broken_link_report,
        internal_link_report=internal_link_report,
        link_sort_labels=LINK_SORT_LABELS,
        image_report=image_report,
        meta_tag_report=meta_tag_report,
        word_count_report=word_count_report,
        canonical_report=canonical_report,
        ga4_metrics=ga4_metrics,
        ga4_report=ga4_report,
        ga4_dimension_labels=GA4_DIMENSION_LABELS,
        ga4_sort_labels=GA4_SORT_LABELS,
        gsc_metrics=gsc_metrics,
        gsc_report=gsc_report,
        gsc_view_labels=GSC_VIEW_LABELS,
        rankings=rankings,
        competitor_rankings=competitor_rankings,
        backlinks=backlinks,
        competitor_backlinks=competitor_backlinks,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/ga4/download')
@login_required
def download_ga4_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    ga4_metrics = db.session.query(Ga4Metric).filter_by(snapshot_id=snapshot_id).order_by(Ga4Metric.metric_name.asc(), Ga4Metric.metric_value.desc()).all()
    ga4_report = _build_ga4_report(ga4_metrics)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Sr. No.",
        ga4_report["dimension_label"],
        "Total Users",
        "Sessions",
        "Average Time Duration",
        "Event Count",
        "Engagement Rate",
    ])

    for index, row in enumerate(ga4_report["rows"], start=1):
        writer.writerow([
            index,
            row["dimension_value"],
            row["metrics"]["totalUsers"] if row["metrics"]["totalUsers"] is not None else "",
            row["metrics"]["sessions"] if row["metrics"]["sessions"] is not None else "",
            row["metrics"]["averageSessionDuration"] if row["metrics"]["averageSessionDuration"] is not None else "",
            row["metrics"]["eventCount"] if row["metrics"]["eventCount"] is not None else "",
            row["metrics"]["engagementRate"] if row["metrics"]["engagementRate"] is not None else "",
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_ga4_{ga4_report['selected_dimension']}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@main_bp.route('/snapshot/<int:snapshot_id>/gsc/download')
@login_required
def download_gsc_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    gsc_metrics = db.session.query(GscMetric).filter_by(snapshot_id=snapshot_id).order_by(GscMetric.impressions.desc()).all()
    gsc_report = _build_gsc_report(gsc_metrics)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sr. No.", gsc_report["view_label"], "Clicks", "Impressions", "CTR", "Average Position"])

    for index, row in enumerate(gsc_report["rows"], start=1):
        writer.writerow([
            index,
            row["label"],
            row["clicks"],
            row["impressions"],
            row["ctr"],
            row["position"] if row["position"] is not None else "",
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_gsc_{gsc_report['selected_view']}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@main_bp.route('/snapshot/<int:snapshot_id>/issues/download')
@login_required
def download_issue_category_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    selected_issue_key = (request.args.get("issue_key") or "").strip()
    if not selected_issue_key:
        flash("Select an issue category before downloading CSV.", "error")
        return redirect(url_for('main.snapshot_detail', snapshot_id=snapshot.id))

    crawl_issues = db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot.id).order_by(CrawlIssue.issue_type.asc(), CrawlIssue.issue.asc(), CrawlIssue.url.asc()).all()
    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot.id).order_by(CrawlPage.url.asc()).all()
    crawl_links = db.session.query(CrawlPageLink).filter_by(snapshot_id=snapshot.id).order_by(CrawlPageLink.source_url.asc(), CrawlPageLink.target_url.asc()).all()
    crawl_images = db.session.query(CrawlPageImage).filter_by(snapshot_id=snapshot.id).order_by(CrawlPageImage.page_url.asc(), CrawlPageImage.position.asc(), CrawlPageImage.image_url.asc()).all()
    crawl_structured_data = db.session.query(CrawlPageStructuredData).filter_by(snapshot_id=snapshot.id).order_by(CrawlPageStructuredData.page_url.asc(), CrawlPageStructuredData.position.asc()).all()
    issue_groups = _build_issue_category_groups(crawl_pages, crawl_links, crawl_images, crawl_structured_data, crawl_issues)

    selected_item = None
    selected_category_slug = ""
    for category in issue_groups:
        for item in category["items"]:
            if item["key"] == selected_issue_key:
                selected_item = item
                selected_category_slug = category["slug"]
                break
        if selected_item:
            break

    if not selected_item:
        flash("No crawl issue rows found for the selected category.", "error")
        return redirect(url_for('main.snapshot_detail', snapshot_id=snapshot.id))

    csv_rows = []
    for index, row in enumerate(selected_item["rows"], start=1):
        csv_rows.append([
            index,
            selected_item["severity"].title(),
            selected_item["label"],
            row.get("url", ""),
            row.get("image_url", ""),
            row.get("target_url", ""),
            row.get("anchor_text", ""),
            row.get("details", ""),
        ])

    safe_issue = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in selected_item["label"]).strip("_") or "issue"
    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_{selected_category_slug}_{safe_issue}.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Severity", "Issue", "URL", "Image URL", "Target URL", "Anchor Text", "Details"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/issues/group-download')
@login_required
def download_issue_group_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    selected_category_slug = (request.args.get("category") or "").strip()
    if not selected_category_slug:
        flash("Select an issue group before downloading CSV.", "error")
        return redirect(url_for('main.snapshot_detail', snapshot_id=snapshot.id))

    crawl_issues = db.session.query(CrawlIssue).filter_by(snapshot_id=snapshot.id).order_by(CrawlIssue.issue_type.asc(), CrawlIssue.issue.asc(), CrawlIssue.url.asc()).all()
    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot.id).order_by(CrawlPage.url.asc()).all()
    crawl_links = db.session.query(CrawlPageLink).filter_by(snapshot_id=snapshot.id).order_by(CrawlPageLink.source_url.asc(), CrawlPageLink.target_url.asc()).all()
    crawl_images = db.session.query(CrawlPageImage).filter_by(snapshot_id=snapshot.id).order_by(CrawlPageImage.page_url.asc(), CrawlPageImage.position.asc(), CrawlPageImage.image_url.asc()).all()
    crawl_structured_data = db.session.query(CrawlPageStructuredData).filter_by(snapshot_id=snapshot.id).order_by(CrawlPageStructuredData.page_url.asc(), CrawlPageStructuredData.position.asc()).all()
    issue_groups = _build_issue_category_groups(crawl_pages, crawl_links, crawl_images, crawl_structured_data, crawl_issues)
    selected_category = next((item for item in issue_groups if item["slug"] == selected_category_slug), None)

    if not selected_category:
        flash("No issue group found for download.", "error")
        return redirect(url_for('main.snapshot_detail', snapshot_id=snapshot.id))

    csv_rows = []
    row_number = 1
    for item in selected_category["items"]:
        for row in item["rows"]:
            csv_rows.append([
                row_number,
                selected_category["title"],
                item["label"],
                item["severity"].title(),
                row.get("url", ""),
                row.get("image_url", ""),
                row.get("target_url", ""),
                row.get("anchor_text", ""),
                row.get("details", ""),
            ])
            row_number += 1

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_{selected_category_slug}.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Group", "Issue", "Severity", "URL", "Image URL", "Target URL", "Anchor Text", "Details"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/links/download')
@login_required
def download_internal_links_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    link_sort = (request.args.get("link_sort") or "unique_internal_links").strip()
    link_order = (request.args.get("link_order") or "desc").strip().lower()
    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    crawl_links = db.session.query(CrawlPageLink).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageLink.source_url.asc(), CrawlPageLink.target_url.asc()).all()
    internal_link_report = _build_internal_link_report(crawl_pages, crawl_links, limit=100000, sort_key=link_sort, sort_order=link_order)

    csv_rows = []
    for index, row in enumerate(internal_link_report["rows"], start=1):
        csv_rows.append([
            index,
            row["url"],
            row["unique_internal_links"],
            row["total_internal_links"],
            row["status_code"] or "",
            row["title"],
            row["word_count"] if row["word_count"] is not None else "",
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_internal_links_{internal_link_report['selected_sort']}.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Page", "Unique Internal Links", "Total Internal Links", "Status", "Title", "Word Count"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/images/download')
@login_required
def download_images_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_images = db.session.query(CrawlPageImage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPageImage.page_url.asc(), CrawlPageImage.position.asc(), CrawlPageImage.image_url.asc()).all()
    image_report = _build_image_report(crawl_images, limit=100000)

    csv_rows = []
    for index, row in enumerate(image_report["rows"], start=1):
        csv_rows.append([
            index,
            row["image_url"],
            row["alt_text"],
            row["alt_state"],
            row["page_url"],
            row["file_size_bytes"] if row["file_size_bytes"] is not None else "",
            row["dimensions"],
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_images.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Image URL", "Alt Text", "Alt State", "Page URL", "File Size Bytes", "Dimensions"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/meta-tags/download')
@login_required
def download_meta_tags_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    meta_tag_report = _build_meta_tag_report(crawl_pages, limit=100000)

    csv_rows = []
    for index, row in enumerate(meta_tag_report["rows"], start=1):
        csv_rows.append([
            index,
            row["url"],
            row["title"],
            row["meta_description"],
            row["title_length"],
            row["meta_length"],
            row["word_count"] if row["word_count"] is not None else "",
            ", ".join(row["flags"]) if row["flags"] else "OK",
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_meta_tags.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Page", "Meta Title", "Meta Description", "Title Length", "Meta Description Length", "Word Count", "Flags"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/word-count/download')
@login_required
def download_word_count_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    word_count_report = _build_word_count_report(crawl_pages, limit=100000)

    csv_rows = []
    for index, row in enumerate(word_count_report["rows"], start=1):
        csv_rows.append([
            index,
            row["url"],
            row["title"],
            row["word_count"] if row["word_count"] is not None else "",
            row["bucket"],
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_word_count.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Page", "Title", "Word Count", "Bucket"],
        csv_rows,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/canonical/download')
@login_required
def download_canonical_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_pages = db.session.query(CrawlPage).filter_by(snapshot_id=snapshot_id).order_by(CrawlPage.url.asc()).all()
    canonical_report = _build_canonical_report(crawl_pages, limit=100000)

    csv_rows = []
    for index, row in enumerate(canonical_report["rows"], start=1):
        csv_rows.append([
            index,
            row["url"],
            row["canonical_url"] or "",
            ", ".join(row["flags"]),
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_canonical.csv"
    return _csv_response(
        filename,
        ["Sr. No.", "Page", "Canonical URL", "Flags"],
        csv_rows,
    )
