import csv
import io
import json
import os
import time
from datetime import date, datetime
from http import HTTPStatus

from flask import Blueprint, Response, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from markupsafe import Markup
import markdown
from sqlalchemy import case, func, or_

from app.models import (
    BacklinkAnchor,
    BacklinkHistory,
    BacklinkItem,
    BacklinkReferringDomain,
    Client,
    Competitor,
    CompetitorCountryTraffic,
    CompetitorInsight,
    CopilotConversation,
    CopilotMessage,
    CopilotRun,
    CrawlIssue,
    CrawlPage,
    CrawlPageImage,
    CrawlPageLink,
    CrawlPageStructuredData,
    Ga4Metric,
    GscMetric,
    Keyword,
    KeywordResearchResult,
    KeywordResearchRun,
    Ranking,
    RankingReconciliationJob,
    Snapshot,
    OnePageAudit,
    db,
)
from services.ai_settings import get_effective_ai_settings
from services.analysis_progress import build_analysis_progress_presentation
from services.audit_status import build_audit_status_summary
from services.ga4 import GA4_REPORT_METRICS as GA4_CACHE_METRICS, get_or_fetch_snapshot_ga4
from services.gsc import get_or_fetch_snapshot_gsc
from services.health import get_latest_health_score, persist_health_score, serialize_health_score
from services.make_pdf import markdown_file_to_pdf_bytes
from services.pipeline_runner import enqueue_snapshot_job
from services.snapshot_service import delete_snapshot as delete_snapshot_service
from services.crawl_scope import build_crawl_scope
from services.copilot_history import (
    DEFAULT_COPILOT_MESSAGE_PAGE_SIZE,
    MAX_COPILOT_MESSAGE_PAGE_SIZE,
    get_copilot_message_page,
)
from services.one_page_runner import enqueue_one_page_audit
from services.keyword_research import (
    BUSINESS_FITS,
    MAX_BULK_KEYWORDS,
    RESULT_PAGE_SIZE,
    create_keyword_research_run,
    language_options as keyword_research_language_options,
    parse_input_keywords,
    update_keyword_research_business_fit,
)
from services.dataforseo_locations import google_location_names
from services.rankings import get_keyword_movement_data, ranking_lookup_key as ranking_service_lookup_key, ranking_movement as ranking_service_movement
from services.trend_analysis import VALID_TREND_WINDOWS, get_project_trends
from services.project_history import get_history_page

main_bp = Blueprint('main', __name__)


def _require_project_access(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
    return client


REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "reports",
)


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

GA4_REPORT_METRICS = list(GA4_CACHE_METRICS)

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

# The snapshot detail can show every affected URL. The Overview needs a more
# actionable summary, so retain one clear next action for every canonical
# issue that the crawler creates.
ISSUE_RECOMMENDATIONS = {
    "meta_title_missing": "Write one unique, descriptive title for each affected page and publish it inside the page <head>.",
    "meta_title_duplicate": "Rewrite duplicate titles so each page has a distinct title that matches its primary intent.",
    "meta_title_over_100": "Shorten the title while keeping the main topic and a useful differentiator near the beginning.",
    "meta_title_below_30": "Expand the title with a clear topic, service, product, or location so it describes the page accurately.",
    "meta_title_outside_head": "Move the title tag into the document <head> and confirm that the rendered page exposes the same title.",
    "meta_description_missing": "Add a unique meta description that summarizes the page and encourages a relevant search click.",
    "meta_description_duplicate": "Rewrite repeated descriptions so searchers can distinguish each page in the results.",
    "meta_description_over_200": "Shorten the description to a concise, unique summary; keep the key benefit and page topic first.",
    "meta_description_below_70": "Expand the description with useful context, a benefit, or a call to action without duplicating another page.",
    "h1_missing": "Add one visible H1 that states the page's main topic and aligns with its search intent.",
    "h1_duplicate": "Make the H1 unique for each affected URL, especially where pages target different services or locations.",
    "multiple_h1s": "Keep one primary H1 and convert secondary headings into an appropriate H2 or lower-level heading.",
    "h2_duplicate": "Rename repeated H2 headings so each section has a clear, distinct purpose.",
    "low_word_count": "Expand the page with original, helpful content that answers the visitor's intent rather than adding filler text.",
    "duplicate_content": "Consolidate near-duplicate pages, rewrite the content for a distinct intent, or use a canonical where appropriate.",
    "missing_canonical": "Add a self-referencing canonical URL, or point it to the preferred equivalent page where duplication is intentional.",
    "canonical_non_200": "Update the canonical target to a live, indexable URL that returns HTTP 200.",
    "image_alt_missing": "Add concise, descriptive alt text to meaningful images; leave purely decorative images empty.",
    "image_over_100kb": "Compress or modernize oversized images and serve responsive dimensions to improve page load time.",
    "broken_links": "Replace, remove, or redirect broken internal links and verify that their destination now returns a successful response.",
    "orphan_pages": "Add relevant internal links from discoverable pages so each important URL has a crawlable path from the site.",
    "deep_pages": "Add contextual internal links or improve navigation so important pages are reachable within a few clicks.",
    "schema_validation_errors": "Validate the structured data, fix invalid properties, and retest it with Google's rich result tools.",
    "4xx_errors": "Restore the page, redirect it to the closest relevant replacement, or remove internal links pointing to it.",
    "5xx_errors": "Investigate the server or application error, restore a stable 200 response, and then re-crawl the affected URLs.",
    "http_urls": "Redirect HTTP URLs to their HTTPS equivalent and update internal links, canonicals, and sitemaps to use HTTPS.",
    "very_long_urls": "Use a shorter, readable URL slug where possible and add a permanent redirect from the old URL if it changes.",
    "underscores_or_mixed_case": "Use one consistent lowercase, hyphen-separated URL convention and redirect any changed legacy URLs.",
    "noindex_pages": "Confirm the page should be excluded; otherwise remove the noindex directive and request reindexing after validation.",
    "robots_blocked_pages": "Review robots.txt rules and unblock important URLs that need to be crawled and indexed.",
    "mobile_page_speed": "Profile the affected pages and reduce render-blocking assets, image weight, and slow server responses.",
}

ISSUE_CATEGORY_RECOMMENDATIONS = {
    "meta-titles": "Review the title template and then tailor exceptions on affected pages.",
    "meta-descriptions": "Review the description template and make each affected page's summary unique.",
    "headings": "Fix the page heading hierarchy so one main heading explains the page topic.",
    "content": "Improve page-level content quality and distinguish overlapping pages.",
    "canonical-tags": "Validate canonical rules and ensure every preferred target can be indexed.",
    "images": "Improve image accessibility and delivery performance.",
    "internal-linking": "Repair the internal link graph so important pages are reachable and links resolve successfully.",
    "errors": "Resolve response errors and check redirects or server configuration before the next crawl.",
    "indexation": "Review indexability directives against the pages that should appear in search.",
}

ISSUE_PRIORITY_LABELS = {
    "high": "High priority",
    "medium": "Medium priority",
    "low": "Low priority",
}


def _ranking_lookup_key(keyword_text, location, device, language="en"):
    return ranking_service_lookup_key(keyword_text, location, device, language)[1:]


def _ranking_movement(current_position, previous_position, current_status="found"):
    """Describe ranking change using the lower-is-better Google position rule."""
    movement = ranking_service_movement(current_position, previous_position, current_status)
    return {
        "change": movement["value"],
        "label": movement["label"],
        "tone": movement["direction"],
    }


def _ranking_row_key(row):
    return (
        row.competitor_id,
        _ranking_lookup_key(row.keyword, row.location, row.device, row.language),
    )


def _build_ranking_movements(current_rows, previous_rows):
    previous_by_key = {_ranking_row_key(row): row for row in previous_rows}
    return {
        row.id: _ranking_movement(
            row.position,
            previous_by_key.get(_ranking_row_key(row)).position
            if previous_by_key.get(_ranking_row_key(row))
            else None,
            row.check_status,
        )
        for row in current_rows
    }


def _build_keyword_rankings(keywords, current_snapshot, previous_snapshot):
    if not current_snapshot:
        return {}

    current_rows = Ranking.query.filter_by(snapshot_id=current_snapshot.id, competitor_id=None).all()
    previous_rows = Ranking.query.filter_by(snapshot_id=previous_snapshot.id, competitor_id=None).all() if previous_snapshot else []

    current_by_keyword = {
        _ranking_lookup_key(row.keyword, row.location, row.device, row.language): row for row in current_rows
    }
    previous_by_keyword = {
        _ranking_lookup_key(row.keyword, row.location, row.device, row.language): row for row in previous_rows
    }

    keyword_rankings = {}
    for keyword in keywords:
        ranking_key = _ranking_lookup_key(keyword.keyword, keyword.location, keyword.device, keyword.language)
        latest = current_by_keyword.get(ranking_key)
        previous = previous_by_keyword.get(ranking_key)

        current_position = latest.position if latest else None
        previous_position = previous.position if previous else None

        check_status = latest.check_status if latest else "not_found"
        movement_state = _ranking_movement(current_position, previous_position, check_status)

        keyword_rankings[keyword.id] = {
            "latest": latest,
            "previous": previous,
            "current_position": current_position,
            "previous_position": previous_position,
            "check_status": check_status,
            "error_message": latest.error_message if latest else None,
            "movement": movement_state["change"],
            "movement_label": movement_state["label"],
            "movement_tone": movement_state["tone"],
        }

    return keyword_rankings


@main_bp.route('/project/<int:client_id>/rankings/data')
@login_required
def keyword_rankings_data(client_id):
    """Return the dashboard ranking contract without triggering a new audit."""
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    return jsonify(get_keyword_movement_data(
        client_id,
        filter_name=request.args.get('filter', 'all'),
        search=request.args.get('search', ''),
        location=request.args.get('location'),
        device=request.args.get('device'),
        page=request.args.get('page', 1, type=int),
        per_page=request.args.get('per_page', 25, type=int),
        history_limit=request.args.get('history_limit', 12, type=int),
    ))


@main_bp.route('/project/<int:client_id>/trends/data')
@login_required
def project_trends_data(client_id):
    """Return stored 30/60/90-day trend data without hitting provider APIs."""
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
    days = request.args.get('days', 30, type=int)
    if days not in VALID_TREND_WINDOWS:
        return jsonify({"error": "days must be 30, 60, or 90"}), 400
    return jsonify(get_project_trends(client_id, days))


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


def _has_usable_page_content(page):
    """Exclude crawler error documents from on-page SEO checks."""
    status_code = getattr(page, "status_code", None)
    if status_code is not None:
        try:
            if not 200 <= int(status_code) < 400:
                return False
        except (TypeError, ValueError):
            pass
    return True


def _has_usable_page_title(page, title):
    if not _has_usable_page_content(page):
        return False
    normalized_title = (title or "").strip().lower()
    return "your access to this site has been limited by the site owner" not in normalized_title


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
        has_usable_content = _has_usable_page_content(page)

        title_is_usable = _has_usable_page_title(page, title)
        if title_is_usable and not title:
            missing_title_rows.append(_issue_row(url, "Missing meta title", "error"))
        elif title_is_usable:
            title_candidates.append((url, title))
            if _meta_length(title) > 100:
                long_title_rows.append(_issue_row(url, f"Title length: {_meta_length(title)}", "warning"))
            if _meta_length(title) < 30:
                short_title_rows.append(_issue_row(url, f"Title length: {_meta_length(title)}", "warning"))

        if title_is_usable and page.meta_tags and isinstance(page.meta_tags, dict):
            title_found = False
            for tag_name in page.meta_tags.keys():
                if "title" in str(tag_name).lower():
                    title_found = True
                    break
            if title and not title_found:
                title_outside_head_rows.append(_issue_row(url, "Title not found inside parsed head metadata", "error"))

        if has_usable_content:
            if not meta_description:
                missing_meta_rows.append(_issue_row(url, "Missing meta description", "error"))
            else:
                meta_candidates.append((url, meta_description))
                meta_description_extra = {
                    "meta_description_length": _meta_length(meta_description),
                    "meta_description": meta_description,
                }
                if _meta_length(meta_description) > 200:
                    long_meta_rows.append(_issue_row(url, meta_description, "info", meta_description_extra))
                if _meta_length(meta_description) < 70:
                    short_meta_rows.append(_issue_row(url, meta_description, "info", meta_description_extra))

            if not h1:
                missing_h1_rows.append(_issue_row(url, "Missing H1", "error"))
            else:
                h1_candidates.append((url, h1))

            if page.h2 and isinstance(page.h2, list):
                normalized_h2 = [(_clean_text(item).lower()) for item in page.h2 if _clean_text(item)]
                if len(normalized_h2) != len(set(normalized_h2)):
                    duplicate_h2_rows.append(_issue_row(url, "Duplicate H2 values detected", "warning"))

            if page.word_count is not None and page.word_count < 200:
                thin_content_rows.append(_issue_row(
                    url,
                    f"Word count: {page.word_count}",
                    "warning",
                    {"word_count": page.word_count, "page_title": title},
                ))

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
        for url, title in items:
            duplicate_title_rows.append(_issue_row(
                url,
                title,
                "error",
                {"meta_title": title},
            ))

    duplicate_meta_rows = []
    for items in _looks_like_duplicate_text_map(meta_candidates):
        for url, normalized in items:
            duplicate_meta_rows.append(_issue_row(
                url,
                normalized,
                "warning",
                {
                    "meta_description_length": _meta_length(normalized),
                    "meta_description": normalized,
                },
            ))

    duplicate_h1_rows = []
    for items in _looks_like_duplicate_text_map(h1_candidates):
        for url, h1 in items:
            duplicate_h1_rows.append(_issue_row(
                url,
                h1,
                "warning",
                {"h1": h1},
            ))

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
        if issue_key in {
            "meta_description_duplicate",
            "meta_description_over_200",
            "meta_description_below_70",
            "low_word_count",
            "h1_duplicate",
        }:
            # Use the page-level fields above for these on-page checks. The raw
            # crawler messages only contain a shortened diagnostic, while the
            # page record provides the exact count and full meta description.
            continue
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


def _build_overview_issue_recommendations(snapshot):
    """Create the priority-first issue summary used on a project's Overview.

    The detailed Snapshot view remains the source for individual affected URLs.
    This summary intentionally aggregates each issue type once, with the count
    and an action a user can take without needing to interpret crawler jargon.
    """
    empty_groups = [
        {"severity": severity, "title": title, "items": [], "count": 0}
        for severity, title in ISSUE_PRIORITY_LABELS.items()
    ]
    if not snapshot:
        return {"snapshot": None, "groups": empty_groups, "total": 0, "has_issues": False}

    issue_categories = _build_issue_category_groups(
        CrawlPage.query.filter_by(snapshot_id=snapshot.id).all(),
        CrawlPageLink.query.filter_by(snapshot_id=snapshot.id).all(),
        CrawlPageImage.query.filter_by(snapshot_id=snapshot.id).all(),
        CrawlPageStructuredData.query.filter_by(snapshot_id=snapshot.id).all(),
        CrawlIssue.query.filter_by(snapshot_id=snapshot.id).all(),
    )

    groups_by_severity = {group["severity"]: group for group in empty_groups}
    for category in issue_categories:
        for item in category["items"]:
            if not item["count"]:
                continue
            severity = item["severity"] if item["severity"] in groups_by_severity else "low"
            recommendation = ISSUE_RECOMMENDATIONS.get(
                item["key"],
                ISSUE_CATEGORY_RECOMMENDATIONS.get(
                    category["slug"],
                    "Review the affected URLs, fix the underlying template or page issue, and run another full audit to verify the result.",
                ),
            )
            groups_by_severity[severity]["items"].append({
                "key": item["key"],
                "label": item["label"],
                "category": category["title"],
                "count": item["count"],
                "recommendation": recommendation,
            })

    for group in empty_groups:
        group["items"].sort(key=lambda item: (-item["count"], item["label"].lower()))
        group["count"] = len(group["items"])

    total = sum(group["count"] for group in empty_groups)
    return {
        "snapshot": snapshot,
        "groups": empty_groups,
        "total": total,
        "has_issues": total > 0,
    }


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
    return os.path.join(REPORTS_DIR, filename)


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
    available_ranges = sorted({
        (_safe_date_text(row.period_end), _safe_date_text(row.period_start))
        for row in default_rows
        if _safe_date_text(row.period_start) and _safe_date_text(row.period_end)
    })
    default_end, default_start = available_ranges[-1] if available_ranges else ("", "")
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
    return row_start == selected_start and row_end == selected_end


def _build_ga4_report(
    ga4_metrics,
    selected_start=None,
    selected_end=None,
    selected_dimension=None,
    selected_sort=None,
    selected_order=None,
):
    date_range = _selected_date_range(ga4_metrics, "ga4")
    if selected_start is not None:
        date_range["selected_start"] = _safe_date_text(selected_start)
    if selected_end is not None:
        date_range["selected_end"] = _safe_date_text(selected_end)

    selected_dimension = (selected_dimension or request.args.get("ga4_dimension", "channel")).strip().lower()
    if selected_dimension not in GA4_DIMENSION_LABELS:
        selected_dimension = "channel"

    selected_sort = (selected_sort or request.args.get("ga4_sort", "sessions")).strip()
    if selected_sort not in GA4_SORT_LABELS:
        selected_sort = "sessions"

    selected_order = (selected_order or request.args.get("ga4_order", "desc")).strip().lower()
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


def _build_gsc_report(
    gsc_metrics,
    selected_start=None,
    selected_end=None,
    selected_view=None,
    selected_sort=None,
    selected_order=None,
):
    date_range = _selected_date_range(gsc_metrics, "gsc")
    if selected_start is not None:
        date_range["selected_start"] = _safe_date_text(selected_start)
    if selected_end is not None:
        date_range["selected_end"] = _safe_date_text(selected_end)

    selected_view = (selected_view or request.args.get("gsc_view", "queries")).strip().lower()
    if selected_view not in GSC_VIEW_LABELS:
        selected_view = "queries"

    selected_sort = (selected_sort or request.args.get("gsc_sort", "impressions")).strip()
    if selected_sort not in GSC_SORT_LABELS:
        selected_sort = "impressions"
    selected_order = (selected_order or request.args.get("gsc_order", "desc")).strip().lower()
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


def _broken_link_status_label(status_code, error_type):
    if status_code == 0 or (status_code is None and error_type):
        return (error_type or "unreachable").replace("_", " ").title()
    try:
        status = HTTPStatus(int(status_code))
        return f"{status.value} {status.phrase}"
    except (TypeError, ValueError):
        return str(status_code or "Unknown")


def _build_broken_link_report(crawl_links, page=1, per_page=50):
    rows = []
    for row in crawl_links:
        status_code = row.target_status
        source = row.target_status_source or ""
        error_type = row.target_error_type or ""
        is_unreachable = status_code == 0 or (status_code is None and error_type and source != "skipped")
        if not is_unreachable and (status_code is None or status_code < 400):
            continue
        rows.append({
            "broken_url": row.target_url or "",
            "final_url": row.target_final_url or "",
            "anchor_text": row.anchor_text or "",
            "source_url": row.source_url or "",
            "status_code": status_code,
            "status_label": _broken_link_status_label(status_code, error_type),
            "error_type": error_type,
            "error_message": row.target_error_message or "",
            "status_source": source or "legacy_crawl",
            "checked_at": row.target_checked_at or "",
            "response_time_ms": row.target_response_time_ms,
            "redirect_count": row.target_redirect_count or 0,
            "link_scope": "Internal" if row.is_internal else "External",
        })

    rows.sort(key=lambda item: (
        0 if item["status_code"] == 0 else 1,
        -int(item["status_code"] or 0),
        item["source_url"],
        item["broken_url"],
    ))
    total = len(rows)
    unreachable = sum(
        1
        for item in rows
        if item["status_code"] == 0 or (item["status_code"] is None and item["error_type"])
    )
    if per_page is None:
        paged_rows = rows
        selected_page = 1
        total_pages = 1
    else:
        per_page = max(1, min(int(per_page), 200))
        total_pages = max(1, (total + per_page - 1) // per_page)
        selected_page = max(1, min(int(page or 1), total_pages))
        start = (selected_page - 1) * per_page
        paged_rows = rows[start:start + per_page]
    return {
        "total": total,
        "http_errors": total - unreachable,
        "unreachable": unreachable,
        "rows": paged_rows,
        "page": selected_page,
        "pages": total_pages,
        "per_page": per_page,
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
    crawl_pages = [
        page for page in _dedupe_crawl_pages(crawl_pages)
        if _has_usable_page_title(page, _clean_text(page.title))
    ]
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


def _available_keyword_research_clients():
    return Client.query.order_by(Client.name.asc()).all() if current_user.role == 'admin' else list(current_user.clients)


def _user_keyword_research_runs(limit=20):
    query = KeywordResearchRun.query
    if current_user.role != 'admin':
        client_ids = [client.id for client in current_user.clients]
        filters = [KeywordResearchRun.created_by_user_id == current_user.id]
        if client_ids:
            filters.append(KeywordResearchRun.client_id.in_(client_ids))
        query = query.filter(or_(*filters))
    return query.order_by(KeywordResearchRun.created_at.desc(), KeywordResearchRun.id.desc()).limit(limit).all()


def _require_keyword_research_access(run_id):
    run = KeywordResearchRun.query.get_or_404(run_id)
    if current_user.role != 'admin':
        allowed_client_ids = {client.id for client in current_user.clients}
        if run.created_by_user_id != current_user.id and run.client_id not in allowed_client_ids:
            abort(403)
    return run


def _keyword_research_detail_redirect(run):
    """Return the user to the same bounded research result page after an action."""
    args = {}
    for name in ("q", "fit", "intent", "metrics", "sort"):
        value = (request.form.get(f"return_{name}") or "").strip()
        if value:
            args[name] = value
    page = request.form.get("return_page", type=int)
    if page and page > 1:
        args["page"] = page
    return redirect(url_for("main.keyword_research_detail", run_id=run.id, **args))


def _keyword_research_tracking_client(run):
    client_id = request.form.get("client_id", type=int) or run.client_id
    client = db.session.get(Client, client_id) if client_id else None
    if not client:
        return None
    if current_user.role != "admin" and client not in current_user.clients:
        abort(403)
    return client


def _track_keyword_research_results(run, client, results):
    """Add unique saved research results to a project without creating audit data.

    Research candidates and tracked keywords use separate storage.  A keyword
    can be added once per project/location/language/device context; every
    caller receives stable created/already-tracked counts for UI feedback.
    """
    added = 0
    already_tracked = 0
    seen_keywords = set()
    for result in results:
        keyword_key = result.keyword.casefold()
        if keyword_key in seen_keywords:
            already_tracked += 1
            continue
        seen_keywords.add(keyword_key)
        existing = Keyword.query.filter(
            Keyword.client_id == client.id,
            func.lower(Keyword.keyword) == keyword_key,
            Keyword.location == run.location,
            Keyword.language == run.language,
            Keyword.device == "desktop",
        ).first()
        if existing:
            already_tracked += 1
            continue
        db.session.add(Keyword(
            client_id=client.id,
            keyword=result.keyword,
            location=run.location,
            language=run.language,
            device="desktop",
            priority="medium",
        ))
        added += 1
    if added:
        db.session.commit()
    return added, already_tracked


def _keyword_research_results(run, result_type):
    return KeywordResearchResult.query.filter_by(
        run_id=run.id,
        result_type=result_type,
    ).order_by(
        KeywordResearchResult.source_rank.is_(None),
        KeywordResearchResult.source_rank.asc(),
        func.lower(KeywordResearchResult.keyword).asc(),
        KeywordResearchResult.id.asc(),
    ).all()


BUSINESS_FIT_FILTERS = {"all", "shortlist", "review", "excluded", "unassessed"}
KEYWORD_RESEARCH_SORTS = {"business_fit", "provider", "volume", "difficulty"}


def _research_keyword_query_text():
    return " ".join((request.args.get("q") or "").split())[:100]


def _keyword_research_business_fit_counts(run):
    counts = {fit: 0 for fit in BUSINESS_FITS}
    rows = db.session.query(
        KeywordResearchResult.business_fit,
        func.count(KeywordResearchResult.id),
    ).filter_by(run_id=run.id, result_type="keyword").group_by(KeywordResearchResult.business_fit).all()
    for fit, count in rows:
        counts[fit if fit in counts else "unassessed"] += int(count)
    return counts


def _keyword_research_keyword_page(run):
    """Return a bounded, server-filtered page without loading the entire table."""
    filters = {
        "q": _research_keyword_query_text(),
        "fit": (request.args.get("fit") or "all").strip().lower(),
        "intent": (request.args.get("intent") or "all").strip().lower(),
        "metrics": (request.args.get("metrics") or "all").strip().lower(),
        "sort": (request.args.get("sort") or "business_fit").strip().lower(),
    }
    if filters["fit"] not in BUSINESS_FIT_FILTERS:
        filters["fit"] = "all"
    if filters["metrics"] not in {"all", "available"}:
        filters["metrics"] = "all"
    if filters["sort"] not in KEYWORD_RESEARCH_SORTS:
        filters["sort"] = "business_fit"

    base_query = KeywordResearchResult.query.filter_by(run_id=run.id, result_type="keyword")
    intent_options = [
        value
        for (value,) in base_query.with_entities(KeywordResearchResult.search_intent).filter(
            KeywordResearchResult.search_intent.isnot(None),
        ).distinct().order_by(KeywordResearchResult.search_intent.asc()).all()
        if value
    ]
    if filters["intent"] not in {"all", *[value.casefold() for value in intent_options]}:
        filters["intent"] = "all"

    query = base_query
    if filters["q"]:
        escaped = filters["q"].casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.filter(func.lower(KeywordResearchResult.keyword).like(f"%{escaped}%", escape="\\"))
    if filters["fit"] == "shortlist":
        query = query.filter(KeywordResearchResult.business_fit.in_(("input", "aligned")))
    elif filters["fit"] == "unassessed":
        query = query.filter(or_(KeywordResearchResult.business_fit == "unassessed", KeywordResearchResult.business_fit.is_(None)))
    elif filters["fit"] != "all":
        query = query.filter(KeywordResearchResult.business_fit == filters["fit"])
    if filters["intent"] != "all":
        query = query.filter(func.lower(KeywordResearchResult.search_intent) == filters["intent"])
    if filters["metrics"] == "available":
        query = query.filter(or_(
            KeywordResearchResult.search_volume.isnot(None),
            KeywordResearchResult.keyword_difficulty.isnot(None),
        ))

    fit_rank = case(
        (KeywordResearchResult.business_fit == "input", 0),
        (KeywordResearchResult.business_fit == "aligned", 1),
        (KeywordResearchResult.business_fit == "review", 2),
        (KeywordResearchResult.business_fit == "unassessed", 3),
        (KeywordResearchResult.business_fit == "excluded", 4),
        else_=3,
    )
    provider_order = (KeywordResearchResult.source_rank.is_(None), KeywordResearchResult.source_rank.asc(), KeywordResearchResult.id.asc())
    if filters["sort"] == "volume":
        order_by = (KeywordResearchResult.search_volume.is_(None), KeywordResearchResult.search_volume.desc(), *provider_order)
    elif filters["sort"] == "difficulty":
        order_by = (KeywordResearchResult.keyword_difficulty.is_(None), KeywordResearchResult.keyword_difficulty.asc(), *provider_order)
    elif filters["sort"] == "provider":
        order_by = provider_order
    else:
        order_by = (fit_rank.asc(), *provider_order)

    total = query.order_by(None).count()
    total_pages = max(1, (total + RESULT_PAGE_SIZE - 1) // RESULT_PAGE_SIZE)
    page = max(1, request.args.get("page", 1, type=int) or 1)
    page = min(page, total_pages)
    items = query.order_by(*order_by).offset((page - 1) * RESULT_PAGE_SIZE).limit(RESULT_PAGE_SIZE).all()
    return {
        "items": items,
        "filters": filters,
        "intent_options": intent_options,
        "business_fit_counts": _keyword_research_business_fit_counts(run),
        "pagination": {
            "page": page,
            "per_page": RESULT_PAGE_SIZE,
            "total": total,
            "total_pages": total_pages,
            "first_item": ((page - 1) * RESULT_PAGE_SIZE + 1) if total else 0,
            "last_item": min(page * RESULT_PAGE_SIZE, total),
            "pages": list(range(1, total_pages + 1)),
        },
    }


@main_bp.route('/keyword-research', methods=['GET', 'POST'])
@login_required
def keyword_research():
    clients = _available_keyword_research_clients()
    locations = google_location_names()
    languages = keyword_research_language_options()
    form = {
        'mode': 'single',
        'keywords': '',
        'location': 'United States',
        'language': 'en',
        'client_id': '',
        'focus_terms': '',
        'exclude_terms': '',
        'force_refresh': False,
    }

    if request.method == 'POST':
        form.update({
            'mode': (request.form.get('mode') or 'single').strip().lower(),
            'keywords': request.form.get('keywords') or '',
            'location': request.form.get('location') or 'United States',
            'language': request.form.get('language') or 'en',
            'client_id': request.form.get('client_id') or '',
            'focus_terms': request.form.get('focus_terms') or '',
            'exclude_terms': request.form.get('exclude_terms') or '',
            'force_refresh': request.form.get('force_refresh') == '1',
        })
        try:
            keywords = parse_input_keywords(form['keywords'], form['mode'])
            client_id = int(form['client_id']) if form['client_id'] else None
            selected_client = db.session.get(Client, client_id) if client_id else None
            if client_id and not selected_client:
                raise ValueError('The selected project no longer exists.')
            if selected_client and current_user.role != 'admin' and selected_client not in current_user.clients:
                abort(403)
            run, reused = create_keyword_research_run(
                created_by_user_id=current_user.id,
                client_id=selected_client.id if selected_client else None,
                mode=form['mode'],
                keywords=keywords,
                location=form['location'],
                language=form['language'],
                focus_terms=form['focus_terms'],
                exclude_terms=form['exclude_terms'],
                force_refresh=form['force_refresh'],
            )
            if reused:
                flash('Showing your matching completed research from the last hour. Select Refresh data to request a new provider run.', 'info')
            else:
                flash('Keyword research was queued. Results will appear here automatically.', 'success')
            return redirect(url_for('main.keyword_research_detail', run_id=run.id))
        except ValueError as exc:
            flash(str(exc), 'error')

    return render_template(
        'keyword_research.html',
        clients=clients,
        locations=locations,
        languages=languages,
        form=form,
        runs=_user_keyword_research_runs(),
        max_bulk_keywords=MAX_BULK_KEYWORDS,
    )


@main_bp.route('/keyword-research/<int:run_id>')
@login_required
def keyword_research_detail(run_id):
    run = _require_keyword_research_access(run_id)
    clients = _available_keyword_research_clients()
    keyword_page = _keyword_research_keyword_page(run)
    return render_template(
        'keyword_research_detail.html',
        run=run,
        clients=clients,
        keyword_results=keyword_page['items'],
        keyword_filters=keyword_page['filters'],
        intent_options=keyword_page['intent_options'],
        business_fit_counts=keyword_page['business_fit_counts'],
        keyword_pagination=keyword_page['pagination'],
        questions=_keyword_research_results(run, 'question'),
        autocomplete=_keyword_research_results(run, 'autocomplete'),
    )


@main_bp.route('/keyword-research/<int:run_id>/business-fit', methods=['POST'])
@login_required
def update_keyword_research_business_fit_settings(run_id):
    run = _require_keyword_research_access(run_id)
    try:
        settings, counts = update_keyword_research_business_fit(
            run,
            focus_terms=request.form.get('focus_terms') or '',
            exclude_terms=request.form.get('exclude_terms') or '',
        )
        flash(
            f"Business-fit labels were updated locally ({counts['aligned']} aligned, {counts['excluded']} excluded). No provider request was made.",
            'success',
        )
    except ValueError as exc:
        flash(str(exc), 'error')
    return redirect(url_for('main.keyword_research_detail', run_id=run.id))


@main_bp.route('/keyword-research/<int:run_id>/state')
@login_required
def keyword_research_state(run_id):
    run = _require_keyword_research_access(run_id)
    return jsonify({
        'id': run.id,
        'status': run.status,
        'progress': run.progress or {},
        'summary': run.summary or {},
        'error_message': run.error_message,
        'updated_at': run.updated_at.isoformat() + 'Z' if run.updated_at else None,
    })


@main_bp.route('/keyword-research/<int:run_id>/download')
@login_required
def download_keyword_research_csv(run_id):
    run = _require_keyword_research_access(run_id)
    rows = []
    for result in _keyword_research_results(run, 'keyword'):
        rows.append([
            result.keyword,
            ', '.join(result.source_types or []),
            result.search_volume if result.search_volume is not None else '',
            result.keyword_difficulty if result.keyword_difficulty is not None else '',
            result.search_intent or '',
            result.cpc if result.cpc is not None else '',
            result.competition if result.competition is not None else '',
            result.source_rank if result.source_rank is not None else '',
            result.business_fit or 'unassessed',
            ', '.join((result.business_matches or {}).get('focus_terms') or []),
            ', '.join((result.business_matches or {}).get('exclude_terms') or []),
        ])
    return _csv_response(
        f'keyword_research_{run.id}_{run.location.replace(" ", "_")}.csv',
        [
            'Keyword', 'Sources', 'Search Volume', 'Keyword Difficulty', 'Intent', 'CPC', 'Competition', 'Source Rank',
            'Business Fit', 'Matched Focus Terms', 'Matched Exclude Terms',
        ],
        rows,
    )


@main_bp.route('/keyword-research/<int:run_id>/results/<int:result_id>/track', methods=['POST'])
@login_required
def add_keyword_research_result_to_track(run_id, result_id):
    run = _require_keyword_research_access(run_id)
    result = KeywordResearchResult.query.filter_by(id=result_id, run_id=run.id, result_type='keyword').first_or_404()
    client = _keyword_research_tracking_client(run)
    if not client:
        flash('Choose a project before adding this keyword to tracking.', 'error')
        return _keyword_research_detail_redirect(run)

    added, already_tracked = _track_keyword_research_results(run, client, [result])
    if not added:
        flash(f'"{result.keyword}" is already tracked for {client.name} in this country, language, and device.', 'info')
    else:
        flash(f'"{result.keyword}" was added to {client.name}. Its first ranking position will be collected in the next audit.', 'success')
    return _keyword_research_detail_redirect(run)


@main_bp.route('/keyword-research/<int:run_id>/results/track', methods=['POST'])
@login_required
def add_keyword_research_results_to_track(run_id):
    """Bulk-add explicitly selected results from the currently visible page."""
    run = _require_keyword_research_access(run_id)
    raw_result_ids = request.form.getlist('result_ids')
    if not raw_result_ids:
        flash('Select at least one saved keyword idea before adding it to tracking.', 'error')
        return _keyword_research_detail_redirect(run)
    if len(raw_result_ids) > RESULT_PAGE_SIZE:
        flash('Choose only results from one visible page at a time.', 'error')
        return _keyword_research_detail_redirect(run)
    try:
        result_ids = list(dict.fromkeys(int(value) for value in raw_result_ids))
    except (TypeError, ValueError):
        flash('One or more selected keyword ideas were invalid. Nothing was added.', 'error')
        return _keyword_research_detail_redirect(run)

    results = KeywordResearchResult.query.filter(
        KeywordResearchResult.run_id == run.id,
        KeywordResearchResult.result_type == 'keyword',
        KeywordResearchResult.id.in_(result_ids),
    ).all()
    if len(results) != len(result_ids):
        flash('One or more selected keyword ideas no longer belong to this research run. Nothing was added.', 'error')
        return _keyword_research_detail_redirect(run)

    client = _keyword_research_tracking_client(run)
    if not client:
        flash('Choose a project before adding selected keywords to tracking.', 'error')
        return _keyword_research_detail_redirect(run)

    added, already_tracked = _track_keyword_research_results(run, client, results)
    if added:
        message = f'Added {added} keyword{"s" if added != 1 else ""} to {client.name}. Their first ranking positions will be collected in the next audit.'
        if already_tracked:
            message += f' {already_tracked} selected keyword{"s were" if already_tracked != 1 else " was"} already tracked in this country, language, and device.'
        flash(message, 'success')
    else:
        flash(f'All {already_tracked} selected keyword{"s are" if already_tracked != 1 else " is"} already tracked for {client.name} in this country, language, and device.', 'info')
    return _keyword_research_detail_redirect(run)


@main_bp.route('/project/<int:client_id>/competitor/<int:competitor_id>')
@login_required
def competitor_detail(client_id, competitor_id):
    client = Client.query.get_or_404(client_id)
    competitor = Competitor.query.filter_by(id=competitor_id, client_id=client.id).first_or_404()
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    insight_history = CompetitorInsight.query.filter_by(
        client_id=client.id,
        competitor_id=competitor.id,
    ).order_by(CompetitorInsight.created_at.desc()).all()
    requested_snapshot_id = request.args.get('snapshot_id', type=int)
    if requested_snapshot_id is not None:
        insight = next((row for row in insight_history if row.snapshot_id == requested_snapshot_id), None)
        if not insight:
            abort(404)
    else:
        # Do not let a failed latest collection hide the most recent usable report.
        insight = next((row for row in insight_history if row.status == 'complete'), None)
        insight = insight or (insight_history[0] if insight_history else None)

    snapshot_ids = [row.snapshot_id for row in insight_history if row.snapshot_id]
    snapshots_by_id = {
        snapshot.id: snapshot
        for snapshot in Snapshot.query.filter(Snapshot.id.in_(snapshot_ids)).all()
    } if snapshot_ids else {}
    tracked_rankings = []
    tracked_backlink = None
    country_traffic = []
    tracked_ranking_movements = {}
    if insight and insight.snapshot_id:
        tracked_rankings = Ranking.query.filter_by(
            snapshot_id=insight.snapshot_id,
            competitor_id=competitor.id,
        ).order_by(Ranking.search_volume.desc().nullslast(), Ranking.keyword.asc()).all()
        tracked_backlink = BacklinkHistory.query.filter_by(
            snapshot_id=insight.snapshot_id,
            competitor_id=competitor.id,
        ).first()
        country_traffic = CompetitorCountryTraffic.query.filter_by(
            snapshot_id=insight.snapshot_id,
            competitor_id=competitor.id,
        ).order_by(CompetitorCountryTraffic.estimated_organic_traffic.desc().nullslast(), CompetitorCountryTraffic.location.asc()).all()
        previous_snapshot = Snapshot.query.filter(
            Snapshot.client_id == client.id,
            Snapshot.id < insight.snapshot_id,
            Snapshot.status.in_(("complete", "partial")),
        ).order_by(Snapshot.id.desc()).first()
        previous_rankings = (
            Ranking.query.filter_by(
                snapshot_id=previous_snapshot.id,
                competitor_id=competitor.id,
            ).all()
            if previous_snapshot else []
        )
        tracked_ranking_movements = _build_ranking_movements(tracked_rankings, previous_rankings)
    return render_template(
        'competitor_detail.html',
        client=client,
        competitor=competitor,
        insight=insight,
        insight_history=insight_history,
        snapshots_by_id=snapshots_by_id,
        summary=(insight.summary if insight else {}) or {},
        ranked_keywords=(insight.ranked_keywords if insight else []) or [],
        top_pages=(insight.top_pages if insight else []) or [],
        tracked_rankings=tracked_rankings,
        tracked_backlink=tracked_backlink,
        country_traffic=country_traffic,
        tracked_ranking_movements=tracked_ranking_movements,
    )


@main_bp.route('/project/<int:client_id>/competitor/<int:competitor_id>/export/<dataset>')
@login_required
def download_competitor_dataset_csv(client_id, competitor_id, dataset):
    """Export one separately stored competitor dataset from the selected insight snapshot."""
    client = Client.query.get_or_404(client_id)
    competitor = Competitor.query.filter_by(id=competitor_id, client_id=client.id).first_or_404()
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    insight_history = CompetitorInsight.query.filter_by(
        client_id=client.id,
        competitor_id=competitor.id,
    ).order_by(CompetitorInsight.created_at.desc()).all()
    requested_snapshot_id = request.args.get('snapshot_id', type=int)
    if requested_snapshot_id is not None:
        insight = next((row for row in insight_history if row.snapshot_id == requested_snapshot_id), None)
    else:
        insight = next((row for row in insight_history if row.status == 'complete'), None)
    if not insight or insight.status != 'complete':
        abort(404)

    filename_base = f"{competitor.domain.replace('.', '_')}_snapshot{insight.snapshot_id or insight.id}"
    tracked_rankings = []
    movements = {}
    tracked_backlink = None
    if insight.snapshot_id:
        tracked_rankings = Ranking.query.filter_by(
            snapshot_id=insight.snapshot_id,
            competitor_id=competitor.id,
        ).order_by(Ranking.search_volume.desc().nullslast(), Ranking.keyword.asc()).all()
        tracked_backlink = BacklinkHistory.query.filter_by(
            snapshot_id=insight.snapshot_id,
            competitor_id=competitor.id,
        ).first()
        previous_snapshot = Snapshot.query.filter(
            Snapshot.client_id == client.id,
            Snapshot.id < insight.snapshot_id,
            Snapshot.status.in_(("complete", "partial")),
        ).order_by(Snapshot.id.desc()).first()
        previous_rankings = (
            Ranking.query.filter_by(snapshot_id=previous_snapshot.id, competitor_id=competitor.id).all()
            if previous_snapshot else []
        )
        movements = _build_ranking_movements(tracked_rankings, previous_rankings)

    if dataset == 'tracked-keyword-checks':
        rows = [
            [
                row.keyword or '',
                row.position if row.position is not None else (
                    'Check failed' if row.check_status == 'failed' else 'Not in top 100'
                ),
                movements.get(row.id, {}).get('label', 'Not in top 100'),
                row.url or '',
                row.search_volume if row.search_volume is not None else '',
                row.location or '',
                row.language or '',
                row.device or '',
                row.check_status or '',
                row.error_message or '',
            ]
            for row in tracked_rankings
        ]
        return _csv_response(
            f'{filename_base}_tracked_keyword_checks.csv',
            ['Keyword', 'Position', 'Movement', 'Ranking URL', 'Search Volume', 'Location', 'Language', 'Device', 'Check Status', 'Failure Reason'],
            rows,
        )

    if dataset == 'ranking-keywords':
        rows = [
            [
                row.get('keyword') or '',
                row.get('position') if row.get('position') is not None else '',
                row.get('url') or '',
                row.get('search_volume') if row.get('search_volume') is not None else '',
                row.get('estimated_traffic') if row.get('estimated_traffic') is not None else '',
                row.get('difficulty') if row.get('difficulty') is not None else '',
            ]
            for row in (insight.ranked_keywords or [])
        ]
        return _csv_response(
            f'{filename_base}_ranking_keywords.csv',
            ['Keyword', 'Position', 'Ranking URL', 'Search Volume', 'Estimated Organic Traffic', 'Keyword Difficulty'],
            rows,
        )

    if dataset == 'top-organic-pages':
        rows = [
            [
                row.get('url') or '',
                row.get('estimated_traffic') if row.get('estimated_traffic') is not None else '',
                row.get('keyword_count') if row.get('keyword_count') is not None else '',
            ]
            for row in (insight.top_pages or [])
        ]
        return _csv_response(
            f'{filename_base}_top_organic_pages.csv',
            ['URL', 'Estimated Organic Traffic', 'Ranking Keywords'],
            rows,
        )

    if dataset == 'backlink-movement':
        rows = [[
            competitor.domain,
            tracked_backlink.total_backlinks if tracked_backlink else '',
            tracked_backlink.referring_domains if tracked_backlink else '',
            tracked_backlink.new_backlinks if tracked_backlink else '',
            tracked_backlink.lost_backlinks if tracked_backlink else '',
        ]]
        return _csv_response(
            f'{filename_base}_backlink_movement.csv',
            ['Competitor', 'Total Backlinks', 'Referring Domains', 'New Backlinks', 'Lost Backlinks'],
            rows,
        )

    if dataset == 'country-traffic':
        country_traffic = (
            CompetitorCountryTraffic.query.filter_by(
                snapshot_id=insight.snapshot_id,
                competitor_id=competitor.id,
            ).order_by(CompetitorCountryTraffic.location.asc()).all()
            if insight.snapshot_id else []
        )
        rows = [[
            row.location,
            row.estimated_organic_traffic if row.estimated_organic_traffic is not None else '',
            row.organic_keyword_count if row.organic_keyword_count is not None else '',
            row.top_10_keyword_count if row.top_10_keyword_count is not None else '',
            row.estimated_traffic_cost if row.estimated_traffic_cost is not None else '',
            row.status,
            row.error_message or '',
        ] for row in country_traffic]
        return _csv_response(
            f'{filename_base}_country_traffic.csv',
            ['Country / Location', 'Estimated Organic Traffic', 'Organic Keywords', 'Top 10 Keywords', 'Estimated Traffic Value', 'Status', 'Error'],
            rows,
        )

    abort(404)

@main_bp.route('/project/<int:client_id>')
@login_required
def project(client_id):
    client = Client.query.get_or_404(client_id)
    
    # Check authorization if not admin
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
        
    active_snapshot = (
        Snapshot.query.filter(
            Snapshot.client_id == client_id,
            Snapshot.status.in_(("pending", "running")),
        ).order_by(Snapshot.created_at.desc(), Snapshot.id.desc()).first()
    )
    # A completed audit can still have DataForSEO Standard tasks processing in
    # the background. Keep that snapshot's progress card visible after a page
    # refresh so the user sees automatic reconciliation rather than a generic
    # partial badge with no live status.
    if not active_snapshot:
        active_snapshot = (
            Snapshot.query.join(RankingReconciliationJob)
            .filter(
                Snapshot.client_id == client_id,
                Snapshot.status == "partial",
                RankingReconciliationJob.status.in_(("pending", "running")),
            )
            .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
            .first()
        )
    effective_ai_settings = get_effective_ai_settings(client.id)
    active_tab = request.args.get('tab', 'overview')
    if active_tab not in {"overview", "trends", "keywords", "history"}:
        active_tab = "overview"

    active_progress = {}
    if active_snapshot:
        try:
            active_notes = json.loads(active_snapshot.notes) if active_snapshot.notes else {}
        except json.JSONDecodeError:
            active_notes = {}
        active_progress = active_notes.get("progress", {}) if isinstance(active_notes, dict) else {}
    active_progress_presentation = build_analysis_progress_presentation(
        active_progress,
        active_snapshot.status if active_snapshot else "idle",
    )

    return render_template(
        'project.html',
        client=client,
        effective_ai_settings=effective_ai_settings,
        active_snapshot=active_snapshot,
        active_progress=active_progress,
        active_progress_presentation=active_progress_presentation,
        active_tab=active_tab,
    )


@main_bp.route('/project/<int:client_id>/overview/health')
@login_required
def project_overview_health(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
    latest_crawl = (
        Snapshot.query.join(CrawlPage, CrawlPage.snapshot_id == Snapshot.id)
        .filter(Snapshot.client_id == client_id, Snapshot.status.in_(("complete", "partial")))
        .order_by(Snapshot.created_at.desc(), Snapshot.id.desc()).first()
    )
    record = get_latest_health_score(client_id)
    # Existing projects are scored lazily once after the v2 migration. Future
    # scores are persisted by the audit worker, so normal dashboard loads stay read-only.
    if latest_crawl and (not record or record.snapshot_id != latest_crawl.id):
        record = persist_health_score(latest_crawl)
    health_score = serialize_health_score(record)
    return jsonify({
        'html': render_template('_overview_health.html', health_score=health_score),
    })


def _copilot_message_payload(message):
    failure = next((citation for citation in (message.citations or [])
                    if isinstance(citation, dict) and citation.get('type') == 'copilot_error'), None)
    return {
        'id': message.id,
        'role': message.role,
        'content': message.content,
        'citations': message.citations or [],
        'failure': {
            'code': failure.get('code'),
            'run_id': failure.get('run_id'),
            'retryable': bool(failure.get('retryable')),
        } if failure else None,
        'created_at': message.created_at.isoformat() if message.created_at else None,
    }


def _copilot_state_arguments():
    """Parse and bound cursor arguments before querying a conversation."""
    def _positive_int(name, default=None):
        raw_value = request.args.get(name)
        if raw_value in (None, ""):
            return default
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive integer.") from exc
        if value < 1:
            raise ValueError(f"{name} must be a positive integer.")
        return value

    before_message_id = _positive_int("before_message_id")
    after_message_id = _positive_int("after_message_id")
    if before_message_id and after_message_id:
        raise ValueError("Use either before_message_id or after_message_id, not both.")
    limit = _positive_int("limit", DEFAULT_COPILOT_MESSAGE_PAGE_SIZE)
    if limit > MAX_COPILOT_MESSAGE_PAGE_SIZE:
        raise ValueError(f"limit must not exceed {MAX_COPILOT_MESSAGE_PAGE_SIZE}.")
    return before_message_id, after_message_id, limit


@main_bp.route('/project/<int:client_id>/copilot/state')
@login_required
def project_copilot_state(client_id):
    _require_project_access(client_id)
    try:
        before_message_id, after_message_id, limit = _copilot_state_arguments()
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    query = CopilotConversation.query.filter_by(client_id=client_id)
    if current_user.role != 'admin':
        query = query.filter_by(created_by_user_id=current_user.id)
    conversation = query.order_by(CopilotConversation.updated_at.desc(), CopilotConversation.id.desc()).first()
    if not conversation:
        return jsonify({
            'conversation': None,
            'messages': [],
            'runs': [],
            'page': {
                'mode': 'after' if after_message_id else ('before' if before_message_id else 'latest'),
                'limit': limit,
                'has_older': False,
                'has_newer': False,
                'oldest_message_id': None,
                'newest_message_id': None,
            },
        })
    message_page = get_copilot_message_page(
        conversation.id,
        before_message_id=before_message_id,
        after_message_id=after_message_id,
        limit=limit,
    )
    runs = (CopilotRun.query.filter_by(conversation_id=conversation.id)
            .filter(CopilotRun.status.in_(('pending', 'running')))
            .order_by(CopilotRun.created_at.desc()).all())
    return jsonify({
        'conversation': {'id': conversation.id, 'title': conversation.title},
        'messages': [_copilot_message_payload(message) for message in message_page['messages']],
        'runs': [{'id': run.id, 'status': run.status, 'error': run.error_message} for run in runs],
        'page': message_page['page'],
    })


@main_bp.route('/project/<int:client_id>/copilot/messages', methods=['POST'])
@login_required
def project_copilot_message(client_id):
    _require_project_access(client_id)
    payload = request.get_json(silent=True) or {}
    content = (payload.get('message') or '').strip()
    if not content or len(content) > 4000:
        return jsonify({'error': 'Message must be between 1 and 4,000 characters.'}), 400
    conversation_id = payload.get('conversation_id')
    conversation = None
    if conversation_id:
        conversation = CopilotConversation.query.filter_by(id=conversation_id, client_id=client_id).first()
        if conversation and current_user.role != 'admin' and conversation.created_by_user_id != current_user.id:
            abort(403)
    if not conversation:
        conversation = CopilotConversation(
            client_id=client_id,
            created_by_user_id=current_user.id,
            title=content[:120],
        )
        db.session.add(conversation)
        db.session.flush()
    active_run = CopilotRun.query.filter(
        CopilotRun.conversation_id == conversation.id,
        CopilotRun.status.in_(('pending', 'running')),
    ).first()
    if active_run:
        return jsonify({'error': 'Wait for the current Copilot response before sending another message.'}), 409
    user_message = CopilotMessage(conversation_id=conversation.id, role='user', content=content)
    db.session.add(user_message)
    db.session.flush()
    run = CopilotRun(
        conversation_id=conversation.id,
        client_id=client_id,
        requested_by_user_id=current_user.id,
        user_message_id=user_message.id,
    )
    conversation.updated_at = datetime.utcnow()
    db.session.add(run)
    db.session.commit()
    return jsonify({
        'conversation_id': conversation.id,
        'message': _copilot_message_payload(user_message),
        'run': {'id': run.id, 'status': run.status},
    }), 202


@main_bp.route('/project/<int:client_id>/copilot/runs/<int:run_id>')
@login_required
def project_copilot_run(client_id, run_id):
    _require_project_access(client_id)
    run = CopilotRun.query.filter_by(id=run_id, client_id=client_id).first_or_404()
    if current_user.role != 'admin' and run.requested_by_user_id != current_user.id:
        abort(403)
    payload = {'id': run.id, 'status': run.status}
    if current_user.role == 'admin':
        payload['error'] = run.error_message
    return jsonify(payload)


@main_bp.route('/project/<int:client_id>/copilot/runs/<int:run_id>/retry', methods=['POST'])
@login_required
def project_copilot_run_retry(client_id, run_id):
    _require_project_access(client_id)
    failed_run = CopilotRun.query.filter_by(id=run_id, client_id=client_id, status='failed').first_or_404()
    if current_user.role != 'admin' and failed_run.requested_by_user_id != current_user.id:
        abort(403)
    if not failed_run.user_message_id:
        return jsonify({'error': 'This Copilot response cannot be retried.'}), 409
    active_run = CopilotRun.query.filter(
        CopilotRun.conversation_id == failed_run.conversation_id,
        CopilotRun.status.in_(('pending', 'running')),
    ).first()
    if active_run:
        return jsonify({'error': 'Wait for the current Copilot response before retrying.'}), 409
    run = CopilotRun(
        conversation_id=failed_run.conversation_id,
        client_id=client_id,
        requested_by_user_id=current_user.id,
        user_message_id=failed_run.user_message_id,
    )
    failed_run.conversation.updated_at = datetime.utcnow()
    db.session.add(run)
    db.session.commit()
    return jsonify({'run': {'id': run.id, 'status': run.status}}), 202


@main_bp.route('/project/<int:client_id>/history/data')
@login_required
def project_history_data(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
    page = get_history_page(
        client_id,
        cursor=request.args.get('cursor'),
        limit=request.args.get('limit', 10, type=int),
    )
    return jsonify({
        'html': render_template('_project_history_items.html', **page),
        'next_cursor': page['next_cursor'],
        'has_more': page['has_more'],
        'total_count': page['total_count'],
    })


@main_bp.route('/project/<int:client_id>/overview/issues')
@login_required
def project_overview_issues(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)
    snapshot = (
        Snapshot.query.join(CrawlPage, CrawlPage.snapshot_id == Snapshot.id)
        .filter(
            Snapshot.client_id == client_id,
            Snapshot.status.in_(("complete", "partial")),
        ).order_by(Snapshot.created_at.desc(), Snapshot.id.desc()).first()
    )
    overview_issues = _build_overview_issue_recommendations(snapshot)
    return jsonify({
        'html': render_template('_overview_issues.html', overview_issues=overview_issues),
        'snapshot_id': snapshot.id if snapshot else None,
    })


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
    writer.writerow([
        "Sr. No.",
        "Keyword",
        "Position",
        "Search Volume",
        "Page Score",
        "Ranking URL",
    ])

    for index, keyword in enumerate(keywords, start=1):
        ranking_state = keyword_rankings.get(keyword.id, {})
        latest = ranking_state.get("latest")
        page_score = _compute_keyword_page_score(latest, crawl_pages_by_url)

        writer.writerow([
            index,
            keyword.keyword,
            latest.position if latest and latest.position is not None else (
                "Check failed" if latest and latest.check_status == "failed" else "Not in top 100"
            ),
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


@main_bp.route('/snapshot/<int:snapshot_id>/rankings/download')
@login_required
def download_snapshot_rankings_csv(snapshot_id):
    """Export the project ranking rows stored by this exact audit snapshot."""
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    rankings = Ranking.query.filter_by(
        snapshot_id=snapshot.id,
        competitor_id=None,
    ).all()
    previous_snapshot = Snapshot.query.filter(
        Snapshot.client_id == client.id,
        Snapshot.id < snapshot.id,
        Snapshot.status.in_(("complete", "partial")),
    ).order_by(Snapshot.id.desc()).first()
    previous_rankings = Ranking.query.filter_by(
        snapshot_id=previous_snapshot.id,
        competitor_id=None,
    ).all() if previous_snapshot else []
    movements = _build_ranking_movements(rankings, previous_rankings)

    def ranking_sort_key(row):
        if row.position is not None:
            return (0, row.position, (row.keyword or '').lower())
        if row.check_status == 'failed':
            return (2, float('inf'), (row.keyword or '').lower())
        return (1, float('inf'), (row.keyword or '').lower())

    rows = []
    for row in sorted(rankings, key=ranking_sort_key):
        failed = row.check_status == 'failed'
        rows.append([
            row.keyword or '',
            row.position if row.position is not None else ('Check failed' if failed else 'Not in top 100'),
            movements.get(row.id, {}).get('label', 'Not in top 100'),
            row.url or '',
            row.search_volume if row.search_volume is not None else '',
            row.location or '',
            row.language or '',
            row.device or '',
            'failed' if failed else ('ranked' if row.position is not None else 'not_found'),
            row.error_message or '',
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_tracked_rankings.csv"
    return _csv_response(
        filename,
        [
            'Keyword',
            'Position',
            'Movement',
            'Ranking URL',
            'Search Volume',
            'Location',
            'Language',
            'Device',
            'Check Status',
            'Failure Reason',
        ],
        rows,
    )


@main_bp.route('/project/<int:client_id>/analyze', methods=['POST'])
@login_required
def analyze(client_id):
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    try:
        run_type = request.form.get("run_type", "full_audit")
        selected_stages = request.form.getlist("selected_stages") or None
        crawl_scope = build_crawl_scope(
            client,
            mode=request.form.get("crawl_mode"),
            targets=request.form.get("crawl_targets"),
        )
        snapshot = enqueue_snapshot_job(
            current_app._get_current_object(),
            client_id,
            crawl_scope=crawl_scope,
            run_type=run_type,
            selected_stages=selected_stages,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for('main.project', client_id=client_id))
    label = {
        "full": "full website crawl",
        "selected_urls": "selected URLs crawl",
        "path": "folder/path crawl",
        "reuse": "reuse of the previous crawl",
    }[crawl_scope["mode"]]
    if run_type == "rank_check":
        label = "ranking-only check"
    flash(f"Analysis queued for snapshot #{snapshot.id} ({label}).", "success")
    return redirect(url_for('main.project', client_id=client_id))


@main_bp.route('/project/<int:client_id>/analysis-progress')
@login_required
def analysis_progress(client_id):
    """Return live progress for a queued or running project analysis."""
    client = Client.query.get_or_404(client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    requested_snapshot_id = request.args.get('snapshot_id', type=int)
    if requested_snapshot_id:
        snapshot = Snapshot.query.filter_by(id=requested_snapshot_id, client_id=client.id).first_or_404()
    else:
        snapshot = Snapshot.query.filter(
            Snapshot.client_id == client.id,
            Snapshot.status.in_(("pending", "running")),
        ).order_by(Snapshot.created_at.desc()).first()

    if not snapshot:
        return jsonify({"snapshot_id": None, "status": "idle", "progress": {}})

    try:
        notes = json.loads(snapshot.notes) if snapshot.notes else {}
    except json.JSONDecodeError:
        notes = {}
    progress = notes.get("progress", {}) if isinstance(notes, dict) else {}
    if not isinstance(progress, dict):
        progress = {}

    return jsonify({
        "snapshot_id": snapshot.id,
        "status": snapshot.status,
        "progress": progress,
        "presentation": build_analysis_progress_presentation(progress, snapshot.status),
    })

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
    delete_started_at = time.perf_counter()

    try:
        delete_snapshot_service(snapshot, filepath)
        current_app.logger.info(
            "Deleted snapshot %s and its stored data in %.2fs",
            snapshot_id,
            time.perf_counter() - delete_started_at,
        )

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
    ga4_metrics = db.session.query(Ga4Metric).filter(
        Ga4Metric.snapshot_id == snapshot_id,
        Ga4Metric.metric_name != "__cache_marker__",
    ).order_by(Ga4Metric.metric_name.asc(), Ga4Metric.metric_value.desc()).all()
    gsc_metrics = db.session.query(GscMetric).filter(
        GscMetric.snapshot_id == snapshot_id,
        or_(GscMetric.query.is_(None), GscMetric.query.notlike('__gsc_cache__::%')),
    ).order_by(GscMetric.impressions.desc()).all()
    rankings = db.session.query(Ranking).filter_by(snapshot_id=snapshot_id, competitor_id=None).order_by(Ranking.search_volume.desc().nullslast(), Ranking.keyword.asc()).all()
    competitor_rankings = db.session.query(Ranking).filter(
        Ranking.snapshot_id == snapshot_id,
        Ranking.competitor_id.isnot(None),
    ).join(Competitor, Ranking.competitor_id == Competitor.id).order_by(Competitor.domain.asc(), Ranking.keyword.asc()).all()
    backlinks = db.session.query(BacklinkHistory).filter_by(snapshot_id=snapshot_id, competitor_id=None).all()
    backlink_items = db.session.query(BacklinkItem).filter_by(snapshot_id=snapshot_id).order_by(
        BacklinkItem.domain_rank.desc(), BacklinkItem.source_domain.asc()
    ).all()
    backlink_referring_domains = db.session.query(BacklinkReferringDomain).filter_by(snapshot_id=snapshot_id).order_by(
        BacklinkReferringDomain.domain_rank.desc(), BacklinkReferringDomain.backlinks.desc()
    ).all()
    backlink_anchors = db.session.query(BacklinkAnchor).filter_by(snapshot_id=snapshot_id).order_by(
        BacklinkAnchor.backlinks.desc(), BacklinkAnchor.anchor_text.asc()
    ).all()
    competitor_backlinks = db.session.query(BacklinkHistory).filter(
        BacklinkHistory.snapshot_id == snapshot_id,
        BacklinkHistory.competitor_id.isnot(None),
    ).join(Competitor, BacklinkHistory.competitor_id == Competitor.id).order_by(Competitor.domain.asc()).all()
    competitor_insights = db.session.query(CompetitorInsight).filter_by(snapshot_id=snapshot_id).all()
    configured_competitors = Competitor.query.filter_by(client_id=client.id).order_by(Competitor.domain.asc()).all()

    previous_snapshot = Snapshot.query.filter(
        Snapshot.client_id == client.id,
        Snapshot.id < snapshot.id,
        Snapshot.status.in_(("complete", "partial")),
    ).order_by(Snapshot.id.desc()).first()
    previous_rankings = (
        db.session.query(Ranking).filter_by(snapshot_id=previous_snapshot.id).all()
        if previous_snapshot else []
    )
    ranking_movements = _build_ranking_movements(rankings, previous_rankings)
    competitor_ranking_movements = _build_ranking_movements(competitor_rankings, previous_rankings)

    backlink_summary = backlinks[0] if backlinks else None
    competitor_rankings_by_id = {}
    for row in competitor_rankings:
        competitor_rankings_by_id.setdefault(row.competitor_id, []).append(row)
    competitor_backlinks_by_id = {row.competitor_id: row for row in competitor_backlinks}
    competitor_insights_by_id = {row.competitor_id: row for row in competitor_insights}
    competitor_monitoring = []
    for competitor in configured_competitors:
        insight = competitor_insights_by_id.get(competitor.id)
        backlink = competitor_backlinks_by_id.get(competitor.id)
        summary = (insight.summary if insight else {}) or {}
        rank_rows = competitor_rankings_by_id.get(competitor.id, [])
        summary_rank_row = next(
            (row for row in rank_rows if row.position is not None),
            rank_rows[0] if rank_rows else None,
        )
        competitor_monitoring.append({
            "competitor": competitor,
            "insight": insight,
            "summary": summary,
            "rank_rows": rank_rows,
            "summary_rank_row": summary_rank_row,
            "backlink": backlink,
        })
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
    broken_link_report = _build_broken_link_report(
        crawl_links,
        page=request.args.get("broken_page", 1, type=int),
    )
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
    if not isinstance(notes, dict):
        notes = {"raw": snapshot.notes}

    return render_template(
        'snapshot_detail.html',
        client=client,
        snapshot=snapshot,
        notes=notes,
        snapshot_status_summary=build_audit_status_summary(snapshot.status, notes),
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
        ranking_movements=ranking_movements,
        competitor_rankings=competitor_rankings,
        competitor_ranking_movements=competitor_ranking_movements,
        backlinks=backlinks,
        backlink_summary=backlink_summary,
        backlink_items=backlink_items,
        backlink_referring_domains=backlink_referring_domains,
        backlink_anchors=backlink_anchors,
        competitor_backlinks=competitor_backlinks,
        competitor_monitoring=competitor_monitoring,
    )


@main_bp.route('/snapshot/<int:snapshot_id>/ga4/query', methods=['POST'])
@login_required
def query_snapshot_ga4(snapshot_id):
    """Return an exact GA4 report range, fetching it once when not cached."""
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    payload = request.get_json(silent=True) or request.form
    start_date = _safe_date_text((payload.get('ga4_start') or '').strip())
    end_date = _safe_date_text((payload.get('ga4_end') or '').strip())
    dimension = (payload.get('ga4_dimension') or 'channel').strip().lower()
    sort_key = (payload.get('ga4_sort') or 'sessions').strip()
    sort_order = (payload.get('ga4_order') or 'desc').strip().lower()

    if not start_date or not end_date:
        return jsonify(error='Choose both a start date and an end date.'), 400
    if start_date > end_date:
        return jsonify(error='The start date must be on or before the end date.'), 400
    if dimension not in GA4_DIMENSION_LABELS:
        return jsonify(error='Unsupported GA4 view requested.'), 400
    if sort_key not in GA4_SORT_LABELS or sort_order not in {'asc', 'desc'}:
        return jsonify(error='Unsupported GA4 sort requested.'), 400

    try:
        rows, source = get_or_fetch_snapshot_ga4(snapshot, client, start_date, end_date, dimension)
    except ValueError as exc:
        return jsonify(error=str(exc)), 422
    except Exception:
        current_app.logger.exception(
            'Unable to retrieve GA4 data for snapshot %s and range %s to %s',
            snapshot.id,
            start_date,
            end_date,
        )
        return jsonify(error='Google Analytics could not return data for this period. Please try again shortly.'), 502

    report = _build_ga4_report(
        rows,
        selected_start=start_date,
        selected_end=end_date,
        selected_dimension=dimension,
        selected_sort=sort_key,
        selected_order=sort_order,
    )
    return jsonify({
        'source': source,
        'report': report,
    })


@main_bp.route('/snapshot/<int:snapshot_id>/gsc/query', methods=['POST'])
@login_required
def query_snapshot_gsc(snapshot_id):
    """Return an exact Search Console range, fetching it once when uncached."""
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)
    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    payload = request.get_json(silent=True) or request.form
    start_date = _safe_date_text((payload.get('gsc_start') or '').strip())
    end_date = _safe_date_text((payload.get('gsc_end') or '').strip())
    view_name = (payload.get('gsc_view') or 'queries').strip().lower()
    sort_key = (payload.get('gsc_sort') or 'impressions').strip()
    sort_order = (payload.get('gsc_order') or 'desc').strip().lower()

    if not start_date or not end_date:
        return jsonify(error='Choose both a start date and an end date.'), 400
    if start_date > end_date:
        return jsonify(error='The start date must be on or before the end date.'), 400
    if view_name not in GSC_VIEW_LABELS:
        return jsonify(error='Unsupported Search Console view requested.'), 400
    if sort_key not in GSC_SORT_LABELS or sort_order not in {'asc', 'desc'}:
        return jsonify(error='Unsupported Search Console sort requested.'), 400

    try:
        rows, source = get_or_fetch_snapshot_gsc(snapshot, client, start_date, end_date, view_name)
    except ValueError as exc:
        return jsonify(error=str(exc)), 422
    except Exception:
        current_app.logger.exception(
            'Unable to retrieve Search Console data for snapshot %s and range %s to %s',
            snapshot.id,
            start_date,
            end_date,
        )
        return jsonify(error='Search Console could not return data for this period. Please try again shortly.'), 502

    report = _build_gsc_report(
        rows,
        selected_start=start_date,
        selected_end=end_date,
        selected_view=view_name,
        selected_sort=sort_key,
        selected_order=sort_order,
    )
    return jsonify({
        'source': source,
        'report': report,
    })


@main_bp.route('/snapshot/<int:snapshot_id>/ga4/download')
@login_required
def download_ga4_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    ga4_metrics = db.session.query(Ga4Metric).filter(
        Ga4Metric.snapshot_id == snapshot_id,
        Ga4Metric.metric_name != "__cache_marker__",
    ).order_by(Ga4Metric.metric_name.asc(), Ga4Metric.metric_value.desc()).all()
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

    gsc_metrics = db.session.query(GscMetric).filter(
        GscMetric.snapshot_id == snapshot_id,
        or_(GscMetric.query.is_(None), GscMetric.query.notlike('__gsc_cache__::%')),
    ).order_by(GscMetric.impressions.desc()).all()
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


@main_bp.route('/snapshot/<int:snapshot_id>/backlinks/download')
@login_required
def download_backlink_csv(snapshot_id):
    """Export one stored backlink-detail dataset for a snapshot as CSV."""
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    dataset = (request.args.get("dataset") or "").strip().lower()
    base_filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}"

    if dataset == "backlinks":
        records = db.session.query(BacklinkItem).filter_by(snapshot_id=snapshot.id).order_by(
            BacklinkItem.domain_rank.desc(), BacklinkItem.source_domain.asc()
        ).all()
        headers = [
            "Source Domain", "Source URL", "Domain Rank", "Anchor Text", "Target URL",
            "Link Type", "First Seen", "Last Seen", "Links Count",
        ]
        rows = [
            [
                record.source_domain or "",
                record.source_url or "",
                record.domain_rank if record.domain_rank is not None else "",
                record.anchor_text or "",
                record.target_url or "",
                "DoFollow" if record.is_dofollow is True else "NoFollow" if record.is_dofollow is False else "",
                record.first_seen or "",
                record.last_seen or "",
                record.links_count if record.links_count is not None else "",
            ]
            for record in records
        ]
        return _csv_response(f"{base_filename}_backlinks.csv", headers, rows)

    if dataset == "referring-domains":
        records = db.session.query(BacklinkReferringDomain).filter_by(snapshot_id=snapshot.id).order_by(
            BacklinkReferringDomain.domain_rank.desc(), BacklinkReferringDomain.backlinks.desc()
        ).all()
        headers = ["Domain", "Backlinks", "Domain Rank", "Domain Created At", "Domain Age Years", "First Seen"]
        rows = [
            [
                record.domain,
                record.backlinks if record.backlinks is not None else "",
                record.domain_rank if record.domain_rank is not None else "",
                record.domain_created_at or "",
                record.domain_age_years if record.domain_age_years is not None else "",
                record.first_seen or "",
            ]
            for record in records
        ]
        return _csv_response(f"{base_filename}_referring_domains.csv", headers, rows)

    if dataset == "anchor-text":
        records = db.session.query(BacklinkAnchor).filter_by(snapshot_id=snapshot.id).order_by(
            BacklinkAnchor.backlinks.desc(), BacklinkAnchor.anchor_text.asc()
        ).all()
        headers = ["Anchor Text", "Referring Domains", "Backlinks", "First Seen", "Lost Date"]
        rows = [
            [
                record.anchor_text or "",
                record.referring_domains if record.referring_domains is not None else "",
                record.backlinks if record.backlinks is not None else "",
                record.first_seen or "",
                record.lost_date or "",
            ]
            for record in records
        ]
        return _csv_response(f"{base_filename}_anchor_text.csv", headers, rows)

    abort(404)


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
            row.get("meta_description_length", ""),
            row.get("meta_description", ""),
            row.get("word_count", ""),
            row.get("page_title", ""),
            row.get("h1", ""),
            row.get("details", ""),
        ])

    safe_issue = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in selected_item["label"]).strip("_") or "issue"
    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_{selected_category_slug}_{safe_issue}.csv"
    return _csv_response(
        filename,
        [
            "Sr. No.", "Severity", "Issue", "URL", "Image URL", "Target URL", "Anchor Text",
            "Meta Description Length", "Meta Description", "Word Count", "Page Title", "H1", "Details",
        ],
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


@main_bp.route('/snapshot/<int:snapshot_id>/broken-links/download')
@login_required
def download_broken_links_csv(snapshot_id):
    snapshot = Snapshot.query.get_or_404(snapshot_id)
    client = Client.query.get_or_404(snapshot.client_id)

    if current_user.role != 'admin' and client not in current_user.clients:
        abort(403)

    crawl_links = db.session.query(CrawlPageLink).filter_by(snapshot_id=snapshot_id).order_by(
        CrawlPageLink.source_url.asc(), CrawlPageLink.target_url.asc()
    ).all()
    report = _build_broken_link_report(crawl_links, per_page=None)
    csv_rows = []
    for index, row in enumerate(report["rows"], start=1):
        csv_rows.append([
            index,
            row["status_label"],
            row["broken_url"],
            row["final_url"],
            row["link_scope"],
            row["anchor_text"],
            row["source_url"],
            row["error_type"],
            row["error_message"],
            row["status_source"],
            row["checked_at"],
            row["response_time_ms"] if row["response_time_ms"] is not None else "",
            row["redirect_count"],
        ])

    filename = f"{client.name.replace(' ', '_')}_snapshot{snapshot.id}_broken_links.csv"
    return _csv_response(
        filename,
        [
            "Sr. No.", "Status", "Target URL", "Final URL", "Scope", "Anchor Text",
            "Source Page", "Error Type", "Error Detail", "Verification Source",
            "Checked At", "Response Time (ms)", "Redirect Count",
        ],
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
