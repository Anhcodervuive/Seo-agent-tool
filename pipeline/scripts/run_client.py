"""LEGACY SQLite entry point. Prefer ``python -m services.audit_worker``.
Full end-to-end run for one client: snapshot (all sources) -> analysis -> report.
Usage: python3 run_client.py <client_id>
This is the single entry point the queue calls per client.
"""
import sqlite3, os, sys, datetime
from run_snapshot import get_client, pull_crawl, pull_ga4, pull_gsc, pull_rankings, log
import analyze

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "seo_agent.db")

def run_client(cid):
    conn = sqlite3.connect(DB)
    client = get_client(conn, cid)
    log(f"=== Running full audit for {client['name']} (client {cid}) ===")
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
            results[label] = n; log(f"  {label}: {n} rows")
        except Exception as e:
            conn.rollback(); results[label] = f"FAILED: {e}"; log(f"  {label} FAILED: {e}")

    ok = all(not str(v).startswith("FAILED") for v in results.values())
    status = "complete" if ok else "partial"
    import json
    conn.execute("UPDATE snapshots SET status=?, notes=? WHERE id=?", (status, json.dumps(results), sid))
    conn.commit()
    log(f"  Snapshot {sid}: {status}")

    # Generate the analysis report from this snapshot
    report_ok = True
    try:
        brief = analyze.build_brief(conn, cid, sid)
        report = analyze.generate(brief)
        os.makedirs(analyze.REPORTS, exist_ok=True)
        fname = os.path.join(analyze.REPORTS, f"{client['name'].replace(' ','_')}_snapshot{sid}.md")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"# SEO Report — {client['name']}\n_Snapshot {sid} · {datetime.datetime.now():%Y-%m-%d}_\n\n{report}\n")
        log(f"  Report saved: {fname}")
    except Exception as e:
        report_ok = False; log(f"  Report FAILED: {e}")

    conn.close()
    return {"snapshot_id": sid, "status": status, "sources": results, "report_ok": report_ok}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 run_client.py <client_id>")
    run_client(int(sys.argv[1]))
