"""
Sequential audit queue. Runs all active clients one at a time,
tracking status so it's always visible.
Usage:
  python3 queue_run.py run    - process all active clients sequentially
  python3 queue_run.py status - show current queue status
"""
import sqlite3, os, sys, datetime
from run_client import run_client

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "seo_agent.db")

def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS queue (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id   INTEGER NOT NULL,
            status      TEXT DEFAULT 'pending',
            snapshot_id INTEGER,
            started_at  TEXT,
            finished_at TEXT,
            error       TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(id)
        )""")
    conn.commit()

def enqueue_active(conn):
    # Clear old pending/running entries, enqueue all active clients fresh
    conn.execute("DELETE FROM queue WHERE status IN ('pending','running')")
    clients = conn.execute("SELECT id FROM clients WHERE active=1 ORDER BY id").fetchall()
    for (cid,) in clients:
        conn.execute("INSERT INTO queue (client_id, status) VALUES (?, 'pending')", (cid,))
    conn.commit()
    return len(clients)

def run_queue():
    conn = sqlite3.connect(DB)
    ensure_table(conn)
    n = enqueue_active(conn)
    print(f"Queued {n} active client(s). Processing sequentially...\n")
    while True:
        row = conn.execute("SELECT q.id, q.client_id, c.name FROM queue q JOIN clients c ON c.id=q.client_id WHERE q.status='pending' ORDER BY q.id LIMIT 1").fetchone()
        if not row:
            break
        qid, cid, name = row
        conn.execute("UPDATE queue SET status='running', started_at=? WHERE id=?", (datetime.datetime.now().isoformat(), qid))
        conn.commit()
        print(f"[RUNNING] {name} (client {cid})")
        try:
            result = run_client(cid)
            conn.execute("UPDATE queue SET status='done', snapshot_id=?, finished_at=? WHERE id=?",
                (result["snapshot_id"], datetime.datetime.now().isoformat(), qid))
            conn.commit()
            print(f"[DONE] {name} — snapshot {result['snapshot_id']} ({result['status']})\n")
        except Exception as e:
            conn.execute("UPDATE queue SET status='failed', error=?, finished_at=? WHERE id=?",
                (str(e), datetime.datetime.now().isoformat(), qid))
            conn.commit()
            print(f"[FAILED] {name} — {e}\n")
    print("Queue complete.")
    show_status(conn)
    conn.close()

def show_status(conn=None):
    close = False
    if conn is None:
        conn = sqlite3.connect(DB); close = True
    ensure_table(conn)
    rows = conn.execute("""
        SELECT c.name, q.status, q.snapshot_id, q.started_at, q.finished_at, q.error
        FROM queue q JOIN clients c ON c.id=q.client_id
        ORDER BY q.id""").fetchall()
    print("\n=== QUEUE STATUS ===")
    if not rows:
        print("  (queue empty)")
    for name, status, sid, start, fin, err in rows:
        line = f"  {name:<20} {status:<9}"
        if sid: line += f" snapshot#{sid}"
        if err: line += f" ERROR: {err}"
        print(line)
    print("====================\n")
    if close: conn.close()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "run":
        run_queue()
    elif cmd == "status":
        show_status()
    else:
        print("Usage: python3 queue_run.py [run|status]")
