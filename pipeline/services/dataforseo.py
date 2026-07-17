"""
DataForSEO helpers for keyword enrichment and live SERP rank checks.
"""
import base64
import re

import requests
import config

SEARCH_VOLUME_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"
SERP_LIVE_URL = "https://api.dataforseo.com/v3/serp/google/organic/live/regular"


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

    Uses DataForSEO Live Google Organic SERP Regular with the `target` field so
    the response only includes matching results for the requested domain/path.
    """
    if not keyword or not target:
        return {"position": None, "url": None}, 0.0

    body = [{
        "keyword": keyword.strip(),
        "location_name": location_name or "United States",
        "language_code": language_code or "en",
        "device": device or "desktop",
        "depth": depth,
        "target": target,
    }]
    data = _post(SERP_LIVE_URL, body, timeout=180)
    cost = data.get("cost", 0.0)

    best_match = None
    for task in data.get("tasks", []):
        for result in task.get("result") or []:
            for item in result.get("items") or []:
                rank = item.get("rank_absolute")
                if rank is None:
                    continue
                if best_match is None or rank < best_match["position"]:
                    best_match = {
                        "position": rank,
                        "url": item.get("url"),
                    }

    return best_match or {"position": None, "url": None}, cost


if __name__ == "__main__":
    test = ["it company in vikhroli", "software development company", "hire developers"]
    result, cost = enrich_keywords(test, location_name="India")
    print(f"Cost of this call: ${cost}")
    for keyword, values in result.items():
        print(f"  {keyword}: {values}")
