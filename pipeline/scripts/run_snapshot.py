"""
Runs a full audit snapshot for one client.
Usage: python3 run_snapshot.py <client_id>
Pulls crawl issues + GA4 + GSC, writes a dated snapshot to the DB.
Each source is isolated: one failure is logged but doesn't abort the others.
DataForSEO rankings added as a separate step next.
"""
import sqlite3, os, sys, json, time, datetime
import requests
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Metric, Dimension, RunReportRequest
from googleapiclient.discovery import build
from dataforseo import enrich_keywords

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "seo_agent.db")
KEY = os.path.join(os.path.dirname(BASE), "credentials", "google-service-account.json")
CRAWLER = "http://127.0.0.1:5080"

def log(msg): print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}")

def get_client(conn, cid):
    r = conn.execute("SELECT id,name,domain,ga4_property_id,gsc_site_url FROM clients WHERE id=?", (cid,)).fetchone()
    if not r: sys.exit(f"No client with id {cid}")
    return {"id":r[0],"name":r[1],"domain":r[2],"ga4":r[3],"gsc":r[4]}

def pull_crawl(conn, sid, domain):
    s = requests.Session()
    s.post(f"{CRAWLER}/api/guest-login", json={}, timeout=30)
    url = f"https://{domain}"
    r = s.post(f"{CRAWLER}/api/start_crawl", json={"url":url}, timeout=30).json()
    if not r.get("success"): raise RuntimeError(f"crawl start failed: {r}")
    cid = r["crawl_id"]
    for _ in range(60):
        time.sleep(5)
        st = s.get(f"{CRAWLER}/api/crawls/{cid}", timeout=30).json()
        if st.get("crawl",{}).get("status") == "completed": break
    issues = st.get("issues", [])
    for it in issues:
        conn.execute("INSERT INTO crawl_issues (snapshot_id,url,issue,issue_type,category,details) VALUES (?,?,?,?,?,?)",
            (sid, it.get("url"), it.get("issue"), it.get("type"), it.get("category"), it.get("details")))
    return len(issues)

def pull_ga4(conn, sid, prop):
    creds = service_account.Credentials.from_service_account_file(KEY)
    client = BetaAnalyticsDataClient(credentials=creds)
    start = (datetime.date.today()-datetime.timedelta(days=28)).isoformat()
    end = datetime.date.today().isoformat()
    req = RunReportRequest(
        property=f"properties/{prop}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        metrics=[Metric(name="sessions"),Metric(name="totalUsers"),Metric(name="screenPageViews")],
        dimensions=[Dimension(name="sessionDefaultChannelGroup")],
    )
    resp = client.run_report(req)
    n=0
    for row in resp.rows:
        chan = row.dimension_values[0].value
        for i,m in enumerate(["sessions","totalUsers","screenPageViews"]):
            conn.execute("INSERT INTO ga4_metrics (snapshot_id,metric_name,metric_value,dimension,period_start,period_end) VALUES (?,?,?,?,?,?)",
                (sid, m, float(row.metric_values[i].value), chan, start, end))
            n+=1
    return n

def pull_gsc(conn, sid, site):
    creds = service_account.Credentials.from_service_account_file(KEY, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    svc = build("searchconsole","v1",credentials=creds)
    end = (datetime.date.today()-datetime.timedelta(days=3))
    start = (end-datetime.timedelta(days=28))
    resp = svc.searchanalytics().query(siteUrl=site, body={
        "startDate":start.isoformat(),"endDate":end.isoformat(),
        "dimensions":["query"],"rowLimit":100}).execute()
    rows = resp.get("rows",[])
    for r in rows:
        conn.execute("INSERT INTO gsc_metrics (snapshot_id,query,page,clicks,impressions,ctr,position,period_start,period_end) VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, r["keys"][0], None, r.get("clicks"), r.get("impressions"), r.get("ctr"), r.get("position"), start.isoformat(), end.isoformat()))
    return len(rows)

def pull_rankings(conn, sid, cid):
    # Enrich the client's GSC queries with search volume via DataForSEO.
    # One batched call = all keywords, charged once.
    rows = conn.execute("SELECT DISTINCT query FROM gsc_metrics WHERE snapshot_id=?", (sid,)).fetchall()
    keywords = [r[0] for r in rows if r[0]]
    if not keywords:
        return 0
    # Location comes from the client record (explicit, set per client).
    row = conn.execute("SELECT location FROM clients WHERE id=?", (cid,)).fetchone()
    loc = (row[0] if row and row[0] else "United States")
    enriched, cost = enrich_keywords(keywords, location_name=loc)
    n = 0
    for kw, d in enriched.items():
        conn.execute("INSERT INTO rankings (snapshot_id, keyword, position, search_volume, url, location) VALUES (?,?,?,?,?,?)",
            (sid, kw, None, d.get("search_volume"), None, loc))
        n += 1
    log(f"  (dataforseo cost: ${cost})")
    return n

def main():
    if len(sys.argv)<2: sys.exit("Usage: python3 run_snapshot.py <client_id>")
    cid = int(sys.argv[1])
    conn = sqlite3.connect(DB)
    client = get_client(conn, cid)
    log(f"Starting snapshot for {client['name']}")
    cur = conn.execute("INSERT INTO snapshots (client_id,status) VALUES (?, 'running')", (cid,))
    sid = cur.lastrowid
    conn.commit()
    results = {}
    for label, fn, args in [
        ("crawl", pull_crawl, (conn, sid, client["domain"])),
        ("ga4", pull_ga4, (conn, sid, client["ga4"])),
        ("gsc", pull_gsc, (conn, sid, client["gsc"])),
        ("rankings", pull_rankings, (conn, sid, cid)),
    ]:
        try:
            n = fn(*args); conn.commit()
            results[label]=n; log(f"  {label}: {n} rows")
        except Exception as e:
            conn.rollback(); results[label]=f"FAILED: {e}"; log(f"  {label} FAILED: {e}")
    ok = all(not str(v).startswith("FAILED") for v in results.values())
    conn.execute("UPDATE snapshots SET status=?, notes=? WHERE id=?",
        ("complete" if ok else "partial", json.dumps(results), sid))
    conn.commit(); conn.close()
    log(f"Snapshot {sid} done: {results}")

if __name__=="__main__":
    main()
