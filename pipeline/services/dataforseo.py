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
    keywords = _clean_keywords(keywords)
    if not keywords:
        return {}, 0.0

    body = [{"location_name": location_name, "keywords": keywords}]
    data = _post(SEARCH_VOLUME_URL, body)
    cost = data.get("cost", 0.0)
    output = {}
    for task in data.get("tasks", []):
        for item in task.get("result") or []:
            keyword = item.get("keyword")
            if keyword:
                output[keyword] = {
                    "search_volume": item.get("search_volume"),
                    "competition": item.get("competition"),
                    "cpc": item.get("cpc"),
                }
    return output, cost


def get_keyword_ranking(keyword, target, location_name="United States", language_code="en", device="desktop", depth=100):
    """
    Return ranking data for one keyword against a target domain or wildcard target.

    Uses DataForSEO Live Google Organic SERP Regular with one valid wildcard
    `target` value so the response only includes matching results for the
    requested domain/path.
    """
    target = normalize_domain_target(target)
    if not keyword or not target:
        return {"position": None, "url": None}, 0.0

    body = [{
        "keyword": keyword.strip(),
        "location_name": location_name or "United States",
        "language_code": language_code or "en",
        "device": device or "desktop",
        "depth": depth,
        "target": f"*{target}*",
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
                if result_url and not _url_matches_domain(result_url, target):
                    continue
                rank = item.get("rank_absolute")
                if rank is None:
                    rank = item.get("rank_group")
                if rank is None:
                    continue
                if best_match is None or rank < best_match["position"]:
                    best_match = {
                        "position": rank,
                        "url": result_url,
                    }

    return best_match or {"position": None, "url": None}, cost


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
    }, float(summary_data.get("cost", 0.0) or 0.0) + float(timeseries_data.get("cost", 0.0) or 0.0)


def _metric_value(payload, key):
    if not isinstance(payload, dict):
        return None
    if key in payload:
        return payload.get(key)
    organic = payload.get('organic')
    return organic.get(key) if isinstance(organic, dict) else None


def get_competitor_insights(target, location_name="United States", language_code="en", limit=100):
    """Fetch ranked keywords, top organic pages, and organic traffic estimates."""
    domain = normalize_domain_target(target)
    if not domain:
        raise RuntimeError('A valid competitor domain is required.')
    base = {
        'target': domain,
        'location_name': location_name or 'United States',
        'language_code': language_code or 'en',
    }
    ranked_data = _post(LABS_RANKED_KEYWORDS_URL, [{**base, 'item_types': ['organic'], 'limit': limit}])
    pages_data = _post(LABS_RELEVANT_PAGES_URL, [{**base, 'item_types': ['organic'], 'limit': 25}])
    overview_data = _post(LABS_DOMAIN_RANK_URL, [base])

    ranked_result = _first_result(ranked_data)
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

    pages_result = _first_result(pages_data)
    top_pages = []
    for item in pages_result.get('items') or []:
        page = item.get('page_address') or item.get('url') or item.get('page')
        if page:
            top_pages.append({
                'url': page,
                'estimated_traffic': _metric_value(item.get('metrics'), 'etv') or _metric_value(item, 'etv'),
                'keyword_count': _metric_value(item.get('metrics'), 'count') or _metric_value(item, 'count'),
            })

    overview = _first_result(overview_data)
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
    cost = sum(float(data.get('cost', 0.0) or 0.0) for data in (ranked_data, pages_data, overview_data))
    return {'target': domain, 'summary': summary, 'ranked_keywords': ranked_keywords, 'top_pages': top_pages}, cost


if __name__ == "__main__":
    test = ["it company in vikhroli", "software development company", "hire developers"]
    result, cost = enrich_keywords(test, location_name="India")
    print(f"Cost of this call: ${cost}")
    for keyword, values in result.items():
        print(f"  {keyword}: {values}")
