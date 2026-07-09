"""
DataForSEO enrichment: takes a list of keywords, returns search volume,
competition, and CPC in a single batched request (charged per request,
not per keyword). Uses the google_ads/search_volume/live endpoint.
"""
import os, requests, base64

DFS_LOGIN = os.environ.get("DFS_LOGIN", "")
DFS_PASS = os.environ.get("DFS_PASS", "")
URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"

def enrich_keywords(keywords, location_name="United States"):
    """Returns dict: keyword -> {search_volume, competition, cpc}. Also returns cost."""
    if not keywords:
        return {}, 0.0
    # DataForSEO limits keyword length/count; cap and clean
    # DataForSEO/Google Ads rules: max 10 words per keyword, reasonable length.
    # One bad keyword rejects the whole batch, so filter strictly.
    import re
    kws = []
    for k in keywords:
        if not k:
            continue
        k = k.strip()
        # Google Ads rejects keywords with symbols like & = ? % # @ etc.
        # Keep only letters, numbers, spaces, and basic punctuation (- ' .).
        if not k or len(k) > 80 or len(k.split()) > 10:
            continue
        if re.search(r"[^\w\s\-'.]", k):
            continue
        kws.append(k)
    kws = kws[:700]
    cred = base64.b64encode(f"{DFS_LOGIN}:{DFS_PASS}".encode()).decode()
    headers = {"Authorization": f"Basic {cred}", "Content-Type": "application/json"}
    body = [{"location_name": location_name, "keywords": kws}]
    r = requests.post(URL, headers=headers, json=body, timeout=120)
    r.raise_for_status()
    data = r.json()
    cost = data.get("cost", 0.0)
    out = {}
    for task in data.get("tasks", []):
        for item in (task.get("result") or []):
            kw = item.get("keyword")
            if kw:
                out[kw] = {
                    "search_volume": item.get("search_volume"),
                    "competition": item.get("competition"),
                    "cpc": item.get("cpc"),
                }
    return out, cost

if __name__ == "__main__":
    # Standalone test with a few keywords
    test = ["it company in vikhroli", "software development company", "hire developers"]
    result, cost = enrich_keywords(test, location_name="India")
    print(f"Cost of this call: ${cost}")
    for k, v in result.items():
        print(f"  {k}: {v}")
