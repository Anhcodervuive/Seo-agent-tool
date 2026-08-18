"""
DataForSEO helpers for keyword enrichment and live SERP rank checks.
"""
import base64
import datetime
import re
from urllib.parse import urlparse

import requests
import config

SEARCH_VOLUME_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
SERP_LIVE_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/regular"
BACKLINK_SUMMARY_URL = "https://api.dataforseo.com/v3/backlinks/summary/live"
BACKLINK_TIMESERIES_URL = "https://api.dataforseo.com/v3/backlinks/timeseries_new_lost_summary/live"
BACKLINKS_LIST_URL = "https://api.dataforseo.com/v3/backlinks/backlinks/live"
BACKLINK_REFERRING_DOMAINS_URL = "https://api.dataforseo.com/v3/backlinks/referring_domains/live"
BACKLINK_ANCHORS_URL = "https://api.dataforseo.com/v3/backlinks/anchors/live"
WHOIS_OVERVIEW_URL = "https://api.dataforseo.com/v3/domain_analytics/whois/overview/live"
LABS_RANKED_KEYWORDS_URL = "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live"
LABS_RELEVANT_PAGES_URL = "https://api.dataforseo.com/v3/dataforseo_labs/google/relevant_pages/live"
LABS_DOMAIN_RANK_URL = "https://api.dataforseo.com/v3/dataforseo_labs/google/domain_rank_overview/live"


def normalize_domain_target(target):
    """Return the bare domain format expected by DataForSEO target fields."""
    raw = (target or '').strip()
    if not raw:
        return ''
    # Ranking callers may pass a wildcard target (for example,
    # ``*example.com*``).  Normalize the domain before the ranking helper
    # adds its single wildcard pair; otherwise the payload becomes
    # ``**example.com**`` and DataForSEO rejects it.
    raw = raw.strip('*').strip()
    if not raw:
        return ''
    parsed = urlparse(raw if '://' in raw else f'https://{raw}')
    domain = (parsed.hostname or '').lower().strip('.')
    return domain[4:] if domain.startswith('www.') else domain


def _headers():
    if not config.DFS_LOGIN or not config.DFS_PASS:
        raise RuntimeError("DFS_LOGIN / DFS_PASS are not configured.")
    cred = base64.b64encode(f"{config.DFS_LOGIN}:{config.DFS_PASS}".encode()).decode()
    return {"Authorization": f"Basic {cred}", "Content-Type": "application/json"}


def _post(url, body, timeout=120):
    response = requests.post(url, headers=_headers(), json=body, timeout=timeout)
    response.raise_for_status()
    data = response.json()

    if data.get("status_code") != 20000:
        raise RuntimeError(data.get("status_message") or f"DataForSEO request failed for {url}")

    task_errors = []
    for task in data.get("tasks", []):
        if task.get("status_code") != 20000:
            task_errors.append(task.get("status_message") or f"Task {task.get('id')} failed")

    if task_errors:
        raise RuntimeError("; ".join(task_errors))

    return data


def _clean_keywords(keywords):
    cleaned = []
    for keyword in keywords:
        if not keyword:
            continue
        keyword = keyword.strip()
        if not keyword or len(keyword) > 80 or len(keyword.split()) > 10:
            continue
        if re.search(r"[^\w\s\-'.]", keyword):
            continue
        cleaned.append(keyword)
    return cleaned[:700]


def enrich_keywords(keywords, location_name="United States"):
    """Returns dict: keyword -> {search_volume, competition, cpc}. Also returns cost."""
    contexts = [
        {"keyword": keyword, "location": location_name, "language": "en"}
        for keyword in keywords
    ]
    enriched, cost = enrich_keyword_contexts(contexts)
    return {
        keyword: enriched.get(_keyword_context_key(keyword, location_name, "en"), {})
        for keyword in _clean_keywords(keywords)
    }, cost


def _keyword_context_key(keyword, location_name, language_code):
    return (
        (keyword or "").strip().casefold(),
        (location_name or "United States").strip().casefold(),
        (language_code or "en").strip().casefold(),
    )


def enrich_keyword_contexts(contexts):
    """Fetch search volume per keyword location/language context in one request."""
    grouped = {}
    for context in contexts:
        keyword = (context.get("keyword") or "").strip()
        location_name = (context.get("location") or "United States").strip()
        language_code = (context.get("language") or "en").strip().lower()
        if not _clean_keywords([keyword]):
            continue
        grouped.setdefault((location_name, language_code), []).append(keyword)

    if not grouped:
        return {}, 0.0

    body = [
        {
            "location_name": location_name,
            "language_code": language_code,
            "keywords": list(dict.fromkeys(keywords)),
        }
        for (location_name, language_code), keywords in grouped.items()
    ]
    data = _post(SEARCH_VOLUME_URL, body)
    output = {}
    for index, task in enumerate(data.get("tasks", [])):
        task_data = task.get("data") or {}
        request_task = body[index] if index < len(body) else {}
        location_name = task_data.get("location_name") or request_task.get("location_name") or "United States"
        language_code = task_data.get("language_code") or request_task.get("language_code") or "en"
        for item in task.get("result") or []:
            keyword = item.get("keyword")
            if keyword:
                output[_keyword_context_key(keyword, location_name, language_code)] = {
                    "search_volume": item.get("search_volume"),
                    "competition": item.get("competition"),
                    "cpc": item.get("cpc"),
                }
    return output, _response_cost(data)


def get_keyword_ranking(keyword, target, location_name="United States", language_code="en", device="desktop", depth=100):
    """
    Return ranking data for one keyword against a target domain or wildcard target.

    Fetches the top organic results and matches the normalized target locally.
    Local matching makes www/non-www and canonical URL variants deterministic.
    """
    target = normalize_domain_target(target)
    if not keyword or not target:
        return {"status": "not_found", "position": None, "url": None}, 0.0

    body = [{
        "keyword": keyword.strip(),
        "location_name": location_name or "United States",
        "language_code": language_code or "en",
        "device": device or "desktop",
        "depth": depth,
    }]
    data = _post(SERP_LIVE_URL, body, timeout=180)
    cost = data.get("cost", 0.0)

    best_match = None
    for task in data.get("tasks", []):
        for result in task.get("result") or []:
            for item in result.get("items") or []:
                item_type = (item.get("type") or "").strip().lower()
                if item_type and item_type != "organic":
                    continue
                result_url = item.get("url")
                result_domain = item.get("domain") or result_url
                if not _url_matches_domain(result_domain, target):
                    continue
                rank = item.get("rank_group")
                if rank is None:
                    rank = item.get("rank_absolute")
                if rank is None:
                    continue
                if best_match is None or rank < best_match["position"]:
                    best_match = {
                        "status": "found",
                        "position": rank,
                        "url": result_url,
                    }

    return best_match or {"status": "not_found", "position": None, "url": None}, cost


def _url_matches_domain(value, target):
    """Return whether a SERP URL belongs to the requested target domain."""
    candidate = urlparse(value if '://' in value else f'https://{value}')
    candidate_domain = (candidate.hostname or '').lower().strip('.')
    if candidate_domain.startswith('www.'):
        candidate_domain = candidate_domain[4:]
    target_domain = normalize_domain_target(target)
    return bool(candidate_domain and target_domain and (
        candidate_domain == target_domain or candidate_domain.endswith(f'.{target_domain}')
    ))


def _first_result(data):
    for task in data.get("tasks", []):
        results = task.get("result") or []
        if results:
            return results[0]
    return {}


def _response_cost(data):
    """Read cost from either the response-level or task-level API shape."""
    total = float(data.get("cost", 0.0) or 0.0)
    if total:
        return total
    return sum(float(task.get("cost", 0.0) or 0.0) for task in data.get("tasks", []))


def get_backlink_metrics(target, date_from=None, date_to=None):
    """Return current backlink totals and recent new/lost backlink activity."""
    if not target:
        return {}, 0.0

    target = normalize_domain_target(target)
    summary_data = _post(BACKLINK_SUMMARY_URL, [{"target": target}])
    summary = _first_result(summary_data)
    start = date_from or (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    end = date_to or datetime.date.today().isoformat()
    timeseries_data = _post(
        BACKLINK_TIMESERIES_URL,
        [{"target": target, "date_from": start, "date_to": end, "group_range": "day"}],
    )

    new_backlinks = 0
    lost_backlinks = 0
    new_referring_domains = 0
    lost_referring_domains = 0
    timeseries_result = _first_result(timeseries_data)
    for item in timeseries_result.get("items") or []:
        new_backlinks += int(item.get("new_backlinks") or 0)
        lost_backlinks += int(item.get("lost_backlinks") or 0)
        new_referring_domains += int(item.get("new_referring_domains") or 0)
        lost_referring_domains += int(item.get("lost_referring_domains") or 0)

    return {
        "target": target,
        "total_backlinks": int(summary.get("backlinks") or 0),
        "referring_domains": int(summary.get("referring_domains") or 0),
        "new_backlinks": new_backlinks,
        "lost_backlinks": lost_backlinks,
        "new_referring_domains": new_referring_domains,
        "lost_referring_domains": lost_referring_domains,
        "period_start": start,
        "period_end": end,
        "rank": summary.get("rank"),
        "spam_score": summary.get("spam_score"),
    }, _response_cost(summary_data) + _response_cost(timeseries_data)


def _result_items(data):
    return _first_result(data).get("items") or []


def _domain_age_years(created_datetime):
    """Return a snapshot-time domain age from DataForSEO's WHOIS timestamp."""
    if not created_datetime:
        return None
    try:
        created = datetime.datetime.strptime(created_datetime, "%Y-%m-%d %H:%M:%S %z").date()
    except (TypeError, ValueError):
        try:
            created = datetime.date.fromisoformat(str(created_datetime)[:10])
        except ValueError:
            return None
    return round(max((datetime.date.today() - created).days, 0) / 365.2425, 1)


def _get_domain_registration_dates(domains):
    """Fetch registration dates in one bounded WHOIS request for domain-age display."""
    normalized = []
    seen = set()
    for domain in domains:
        value = normalize_domain_target(domain)
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    if not normalized:
        return {}, 0.0

    data = _post(
        WHOIS_OVERVIEW_URL,
        [{
            "limit": min(len(normalized), 1000),
            "filters": [["domain", "in", normalized]],
        }],
        timeout=180,
    )
    dates = {}
    for item in _result_items(data):
        domain = normalize_domain_target(item.get("domain"))
        if domain:
            dates[domain] = item.get("created_datetime")
    return dates, _response_cost(data)


def get_backlink_detail_report(target, limit=100):
    """Return a bounded, snapshot-ready backlink report for a project domain.

    The report deliberately captures a representative top slice once during an
    analysis run. The UI then reads the stored snapshot rows instead of making
    paid, slow API calls every time a user opens the page.
    """
    domain = normalize_domain_target(target)
    if not domain:
        raise RuntimeError("A valid project domain is required for backlink details.")

    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit = 100

    backlinks_data = _post(
        BACKLINKS_LIST_URL,
        [{
            "target": domain,
            "limit": limit,
            "mode": "as_is",
            "exclude_internal_backlinks": True,
            "rank_scale": "one_hundred",
            "order_by": ["domain_from_rank,desc", "page_from_rank,desc"],
        }],
        timeout=180,
    )
    referring_domains_data = _post(
        BACKLINK_REFERRING_DOMAINS_URL,
        [{
            "target": domain,
            "limit": limit,
            "exclude_internal_backlinks": True,
            "rank_scale": "one_hundred",
            "order_by": ["rank,desc", "backlinks,desc"],
        }],
        timeout=180,
    )
    anchors_data = _post(
        BACKLINK_ANCHORS_URL,
        [{
            "target": domain,
            "limit": limit,
            "order_by": ["backlinks,desc"],
        }],
        timeout=180,
    )

    backlink_items = _result_items(backlinks_data)
    referring_domain_items = _result_items(referring_domains_data)
    anchor_items = _result_items(anchors_data)
    cost = sum(_response_cost(data) for data in (
        backlinks_data,
        referring_domains_data,
        anchors_data,
    ))

    warnings = []
    registration_dates = {}
    try:
        registration_dates, whois_cost = _get_domain_registration_dates(
            [item.get("domain") for item in referring_domain_items]
        )
        cost += whois_cost
    except Exception as exc:
        # WHOIS enrichment is useful for Domain Age but should not discard the
        # three core backlink tables if a particular account cannot use it.
        warnings.append(f"Domain age was unavailable: {exc}")

    backlinks = []
    for item in backlink_items:
        backlinks.append({
            "source_domain": item.get("domain_from"),
            "source_url": item.get("url_from"),
            "domain_rank": item.get("domain_from_rank"),
            "anchor_text": item.get("anchor") or item.get("alt") or "",
            "target_url": item.get("url_to"),
            "is_dofollow": item.get("dofollow"),
            "first_seen": item.get("first_seen"),
            "last_seen": item.get("last_seen"),
            "links_count": item.get("links_count"),
        })

    referring_domains = []
    for item in referring_domain_items:
        item_domain = item.get("domain")
        created_at = registration_dates.get(normalize_domain_target(item_domain))
        referring_domains.append({
            "domain": item_domain,
            "backlinks": item.get("backlinks") or 0,
            "domain_rank": item.get("rank"),
            "domain_created_at": created_at,
            "domain_age_years": _domain_age_years(created_at),
            "first_seen": item.get("first_seen"),
        })

    anchors = []
    for item in anchor_items:
        anchors.append({
            "anchor_text": item.get("anchor") or "",
            "referring_domains": item.get("referring_domains") or 0,
            "backlinks": item.get("backlinks") or 0,
            "first_seen": item.get("first_seen"),
            # The DataForSEO anchor endpoint exposes lost_date rather than a
            # last_seen timestamp. A null value means the anchor is live.
            "lost_date": item.get("lost_date"),
        })

    return {
        "target": domain,
        "limit": limit,
        "backlinks": backlinks,
        "referring_domains": referring_domains,
        "anchors": anchors,
        "warnings": warnings,
    }, cost


def _metric_value(payload, key):
    if not isinstance(payload, dict):
        return None
    if key in payload:
        return payload.get(key)
    organic = payload.get('organic')
    return organic.get(key) if isinstance(organic, dict) else None


def get_competitor_insights(target, location_name="United States", language_code="en", limit=100):
    """Fetch competitor datasets independently so one provider failure is non-fatal."""
    domain = normalize_domain_target(target)
    if not domain:
        raise RuntimeError('A valid competitor domain is required.')
    base = {
        'target': domain,
        'location_name': location_name or 'United States',
        'language_code': language_code or 'en',
    }
    datasets = {
        'ranked keywords': (LABS_RANKED_KEYWORDS_URL, [{**base, 'item_types': ['organic'], 'limit': limit}]),
        'top organic pages': (LABS_RELEVANT_PAGES_URL, [{**base, 'item_types': ['organic'], 'limit': 25}]),
        'organic traffic overview': (LABS_DOMAIN_RANK_URL, [base]),
    }
    responses = {}
    dataset_errors = {}
    total_cost = 0.0
    for label, (url, payload) in datasets.items():
        try:
            response = _post(url, payload)
            responses[label] = response
            total_cost += float(response.get('cost', 0.0) or 0.0)
        except Exception as exc:
            dataset_errors[label] = str(exc)[:1000]

    if len(dataset_errors) == len(datasets):
        raise RuntimeError('; '.join(f'{label}: {error}' for label, error in dataset_errors.items()))

    ranked_result = _first_result(responses.get('ranked keywords', {}))
    ranked_keywords = []
    for item in ranked_result.get('items') or []:
        keyword_data = item.get('keyword_data') or {}
        serp_data = item.get('ranked_serp_element') or {}
        serp_item = serp_data.get('serp_item') or {}
        properties = keyword_data.get('keyword_properties') or {}
        ranked_keywords.append({
            'keyword': keyword_data.get('keyword') or item.get('keyword'),
            'position': serp_item.get('rank_absolute') or serp_data.get('rank_absolute') or item.get('rank_absolute'),
            'url': serp_item.get('url') or serp_data.get('url') or item.get('url'),
            'search_volume': (keyword_data.get('keyword_info') or {}).get('search_volume'),
            'estimated_traffic': _metric_value(item.get('rank_info'), 'etv'),
            'difficulty': properties.get('keyword_difficulty'),
        })

    pages_result = _first_result(responses.get('top organic pages', {}))
    top_pages = []
    for item in pages_result.get('items') or []:
        page = item.get('page_address') or item.get('url') or item.get('page')
        if page:
            top_pages.append({
                'url': page,
                'estimated_traffic': _metric_value(item.get('metrics'), 'etv') or _metric_value(item, 'etv'),
                'keyword_count': _metric_value(item.get('metrics'), 'count') or _metric_value(item, 'count'),
            })

    overview = _first_result(responses.get('organic traffic overview', {}))
    organic = overview.get('organic') or (overview.get('metrics') or {}).get('organic') or {}
    summary = {
        'estimated_organic_traffic': organic.get('etv') or overview.get('etv') or 0,
        'organic_keyword_count': organic.get('count') or overview.get('count') or len(ranked_keywords),
        'position_1': organic.get('pos_1', 0),
        'position_2_3': organic.get('pos_2_3', 0),
        'position_4_10': organic.get('pos_4_10', 0),
        'position_11_20': organic.get('pos_11_20', 0),
        'estimated_paid_traffic_cost': organic.get('estimated_paid_traffic_cost', 0),
    }
    return {
        'target': domain,
        'summary': summary,
        'ranked_keywords': ranked_keywords,
        'top_pages': top_pages,
        'dataset_errors': dataset_errors,
    }, total_cost


def get_competitor_country_traffic(target, location_name, language_code="en"):
    """Return an estimated organic traffic summary for one Google country.

    This deliberately uses the lightweight domain overview endpoint rather
    than collecting ranked keywords and pages again for every extra market.
    """
    domain = normalize_domain_target(target)
    if not domain:
        raise RuntimeError('A valid competitor domain is required.')
    data = _post(LABS_DOMAIN_RANK_URL, [{
        'target': domain,
        'location_name': location_name,
        'language_code': language_code or 'en',
    }])
    overview = _first_result(data)
    organic = overview.get('organic') or (overview.get('metrics') or {}).get('organic') or {}
    top_10 = sum(organic.get(key, 0) or 0 for key in ('pos_1', 'pos_2_3', 'pos_4_10'))
    return {
        'location': location_name,
        'estimated_organic_traffic': organic.get('etv') or overview.get('etv'),
        'organic_keyword_count': organic.get('count') or overview.get('count'),
        'top_10_keyword_count': top_10,
        'estimated_traffic_cost': organic.get('estimated_paid_traffic_cost') or overview.get('estimated_paid_traffic_cost'),
    }, _response_cost(data)


if __name__ == "__main__":
    test = ["it company in vikhroli", "software development company", "hire developers"]
    result, cost = enrich_keywords(test, location_name="India")
    print(f"Cost of this call: ${cost}")
    for keyword, values in result.items():
        print(f"  {keyword}: {values}")
