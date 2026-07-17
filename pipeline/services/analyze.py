"""
Generates an SEO analysis report for a client's latest snapshot.
Usage: python3 analyze.py <client_id>
Pre-processes raw snapshot data into a brief, then asks the LLM for
prioritized recommendations. Saves the report to reports/.
"""
import sqlite3, os, sys, json, datetime, requests
from collections import Counter
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL
from services.ai_settings import DEFAULT_SYSTEM_PROMPT
try:
    from services.trends import compute_trends, compute_trends_from_models
except ImportError:
    from trends import compute_trends
    compute_trends_from_models = None
from app.models import Client, CrawlIssue, Ga4Metric, GscMetric, Ranking, db

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "seo_agent.db")
REPORTS = os.path.join(BASE, "reports")
os.makedirs(REPORTS, exist_ok=True)

def latest_snapshot(conn, cid):
    r = conn.execute("SELECT id,run_date FROM snapshots WHERE client_id=? AND status IN ('complete','partial') ORDER BY run_date DESC LIMIT 1",(cid,)).fetchone()
    if not r: sys.exit(f"No completed snapshot for client {cid}")
    return r[0], r[1]

def build_brief(conn, cid, sid):
    client = conn.execute("SELECT name,domain,business_context FROM clients WHERE id=?",(cid,)).fetchone()
    # Crawl: summarize by issue type + severity, not all rows
    issues = conn.execute("SELECT issue,issue_type FROM crawl_issues WHERE snapshot_id=?",(sid,)).fetchall()
    by_issue = Counter(i[0] for i in issues)
    by_sev = Counter(i[1] for i in issues)
    top_issues = by_issue.most_common(15)
    # GA4: channel breakdown for sessions
    ga4 = conn.execute("SELECT dimension,metric_value FROM ga4_metrics WHERE snapshot_id=? AND metric_name='sessions' ORDER BY metric_value DESC",(sid,)).fetchall()
    # GSC: opportunities = high impressions, low position or low CTR
    gsc = conn.execute("SELECT query,clicks,impressions,ctr,position FROM gsc_metrics WHERE snapshot_id=? ORDER BY impressions DESC LIMIT 30",(sid,)).fetchall()
    opportunities = [g for g in gsc if g[2] and g[2]>50 and (g[4] is None or g[4]>5)]
    # Search volume per keyword from DataForSEO (rankings table)
    vol_rows = conn.execute("SELECT keyword, search_volume FROM rankings WHERE snapshot_id=? AND search_volume IS NOT NULL ORDER BY search_volume DESC", (sid,)).fetchall()
    search_volume = [{"keyword": k, "monthly_searches": v} for k, v in vol_rows[:25]]
    # Striking distance: ranking positions 11-20 (page 2) with real impressions.
    # These are the highest-ROI targets - already ranking, just off page 1.
    striking = [g for g in gsc if g[4] is not None and 10.5 <= g[4] <= 20.5 and g[2] and g[2] >= 10]
    striking.sort(key=lambda g: g[2], reverse=True)
    brief = {
        "client": client[0], "domain": client[1], "business_context": client[2] or "(no context provided)",
        "crawl_summary": {
            "total_issues": len(issues),
            "by_severity": dict(by_sev),
            "top_issue_types": [{"issue":i,"count":c} for i,c in top_issues],
        },
        "traffic_by_channel": [{"channel":d or "(unknown)","sessions":int(v)} for d,v in ga4],
        "top_search_queries": [{"query":g[0],"clicks":g[1],"impressions":g[2],"ctr":round(g[3],4) if g[3] else 0,"position":round(g[4],1) if g[4] else None} for g in gsc[:15]],
        "ranking_opportunities": [{"query":g[0],"impressions":g[2],"position":round(g[4],1) if g[4] else None,"clicks":g[1]} for g in opportunities[:15]],
        "striking_distance_keywords": [{"query":g[0],"impressions":g[2],"position":round(g[4],1),"clicks":g[1],"ctr":round(g[3],4) if g[3] else 0} for g in striking[:15]],
        "keyword_search_volume": search_volume,
    }
    trend = compute_trends(conn, cid)
    if trend:
        brief['month_over_month_trends'] = trend
    return brief


def build_brief_from_models(cid, sid):
    client = db.session.get(Client, cid)
    if not client:
        raise ValueError(f"No client with id {cid}")

    issues = db.session.query(CrawlIssue).filter_by(snapshot_id=sid).all()
    by_issue = Counter(item.issue for item in issues if item.issue)
    by_sev = Counter(item.issue_type for item in issues if item.issue_type)
    ga4_rows = (
        db.session.query(Ga4Metric).filter_by(snapshot_id=sid, metric_name='sessions')
        .order_by(Ga4Metric.metric_value.desc())
        .all()
    )
    gsc_rows = (
        db.session.query(GscMetric).filter_by(snapshot_id=sid)
        .order_by(GscMetric.impressions.desc())
        .limit(30)
        .all()
    )
    opportunities = [row for row in gsc_rows if row.impressions and row.impressions > 50 and (row.position is None or row.position > 5)]
    striking = [row for row in gsc_rows if row.position is not None and 10.5 <= row.position <= 20.5 and row.impressions and row.impressions >= 10]
    striking.sort(key=lambda row: row.impressions, reverse=True)
    ranking_rows = (
        db.session.query(Ranking).filter(Ranking.snapshot_id == sid, Ranking.search_volume.isnot(None))
        .order_by(Ranking.search_volume.desc())
        .all()
    )

    brief = {
        "client": client.name,
        "domain": client.domain,
        "business_context": client.business_context or "(no context provided)",
        "crawl_summary": {
            "total_issues": len(issues),
            "by_severity": dict(by_sev),
            "top_issue_types": [{"issue": issue, "count": count} for issue, count in by_issue.most_common(15)],
        },
        "traffic_by_channel": [{"channel": row.dimension or "(unknown)", "sessions": int(row.metric_value or 0)} for row in ga4_rows],
        "top_search_queries": [{"query": row.query, "clicks": row.clicks, "impressions": row.impressions, "ctr": round(row.ctr, 4) if row.ctr else 0, "position": round(row.position, 1) if row.position else None} for row in gsc_rows[:15]],
        "ranking_opportunities": [{"query": row.query, "impressions": row.impressions, "position": round(row.position, 1) if row.position else None, "clicks": row.clicks} for row in opportunities[:15]],
        "striking_distance_keywords": [{"query": row.query, "impressions": row.impressions, "position": round(row.position, 1), "clicks": row.clicks, "ctr": round(row.ctr, 4) if row.ctr else 0} for row in striking[:15]],
        "keyword_search_volume": [{"keyword": row.keyword, "monthly_searches": row.search_volume} for row in ranking_rows[:25]],
    }
    if compute_trends_from_models:
        trend = compute_trends_from_models(cid)
        if trend:
            brief["month_over_month_trends"] = trend
    return brief

SYSTEM = """You are a senior SEO strategist analysing a client's monthly performance data for an agency. \
You are given a structured brief containing technical crawl issues, traffic by channel (GA4), and search performance (Google Search Console). \
Produce a concise, actionable report for the agency's fulfilment team. Be specific and prioritise ruthlessly. Structure your response as:

## Executive Summary
2-3 sentences on the site's current SEO health, and if month_over_month_trends data is present, explicitly state whether the site is improving or declining overall and by how much (cite the actual figures).

## Top Priorities (ranked)
The 3-5 highest-impact actions, most important first. For each: what to do, why it matters, and an impact rating of High, Medium, or Low with a one-line justification. Ground each in the data (cite the specific issue counts, queries, or metrics). Do NOT invent percentage figures or numeric forecasts — if you don't have data for a number, describe impact qualitatively.

## Quick Wins
2-4 low-effort, high-return actions.

## Ranking Opportunities
Specific queries where the site ranks on page 1-2 with high impressions but could gain clicks with optimisation. Name the queries. IMPORTANT: only include queries clearly relevant to the client's actual business (given by domain and business context). Explicitly ignore and do not recommend action on irrelevant or spammy queries (e.g. unrelated products, gambling, adult, or off-topic terms that appear due to scraper noise) — if you notice such queries in the data, briefly note they appear to be noise rather than real opportunities.

## Striking Distance Keywords (highest priority opportunities)
These are queries currently ranking in positions 11-20 (page 2) with real impressions - the site is close to page 1 and small optimisations can produce outsized traffic gains. From the striking_distance_keywords data, name the most promising RELEVANT ones (ignore noise/spam queries), state their current position and impressions, and give a specific action for each (e.g. strengthen on-page targeting, add internal links, expand content). Prioritise these highly - they are usually the fastest route to more organic traffic.

## Highest-Value Opportunities by Search Demand
Using the keyword_search_volume data (real monthly Google search volume from DataForSEO), identify the keywords with genuine commercial value: high monthly search volume AND relevance to the client's business. A keyword with 5,000 monthly searches that the client is relevant for is far more valuable than one with 30. Cross-reference these against where the client already appears (search queries and striking distance) to find the biggest wins: high search demand + already ranking = top priority. Name specific keywords with their monthly search volume, and ignore high-volume but irrelevant/noise terms.

## Technical Health
Brief note on the crawl issues that matter most.

## Month-over-Month Trend
If month_over_month_trends data is present, summarise what changed since the previous snapshot: traffic (sessions), search clicks/impressions/position, technical issues resolved or introduced, and notable keyword position gains or losses. Be specific with numbers. If a metric declined, flag it clearly as needing attention. If there is only one snapshot (no trend data), state that this is the baseline snapshot and trends will be available next month.

Do not invent data. Only use what is in the brief. Keep it tight and practical."""

def generate(brief, model_name=None, system_prompt=None):
    effective_system_prompt = SYSTEM
    if system_prompt:
        effective_system_prompt = f"{system_prompt.strip()}\n\n{SYSTEM}"

    payload = {
        "model": model_name or OPENROUTER_MODEL,
        "messages": [
            {"role":"system","content":effective_system_prompt},
            {"role":"user","content":"Here is the client's SEO data brief:\n\n"+json.dumps(brief,indent=2)},
        ],
        "temperature": 0.4,
    }
    headers = {"Authorization":f"Bearer {OPENROUTER_API_KEY}","Content-Type":"application/json"}
    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def main():
    if len(sys.argv)<2: sys.exit("Usage: python3 analyze.py <client_id>")
    cid = int(sys.argv[1])
    conn = sqlite3.connect(DB)
    sid, run_date = latest_snapshot(conn, cid)
    brief = build_brief(conn, cid, sid)
    print(f"Analysing {brief['client']} (snapshot {sid}, {run_date})...")
    report = generate(brief)
    conn.close()
    fname = os.path.join(REPORTS, f"{brief['client'].replace(' ','_')}_snapshot{sid}.md")
    with open(fname,"w", encoding="utf-8") as f:
        f.write(f"# SEO Report — {brief['client']}\n_Snapshot {sid} · {run_date}_\n\n{report}\n")
    print(f"Report saved: {fname}\n")
    print("="*60)
    print(report)

if __name__=="__main__":
    main()
