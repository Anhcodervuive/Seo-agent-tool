"""
Lightweight web interface for the SEO agent.
Views: projects list, per-project trends, per-project chat.
Reuses the existing pipeline (DB, analyze, trends).
Run: python3 app.py  (serves on port 8080)
"""
import sqlite3, os, json, datetime, requests
from flask import Flask, render_template_string, request, jsonify
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_URL
import analyze, trends

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "seo_agent.db")

app = Flask(__name__)

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def current_model():
    conn = db()
    r = conn.execute("SELECT value FROM settings WHERE key='model'").fetchone()
    conn.close()
    return r["value"] if r else OPENROUTER_MODEL

AVAILABLE_MODELS = [
    ("z-ai/glm-5.2", "GLM 5.2"),
    ("moonshotai/kimi-k2", "Kimi K2"),
    ("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B"),
    ("deepseek/deepseek-chat", "DeepSeek Chat"),
]

@app.route("/")
def index():
    conn = db()
    clients = conn.execute("""
        SELECT c.id, c.name, c.domain, c.location,
          (SELECT COUNT(*) FROM snapshots s WHERE s.client_id=c.id AND s.status IN ('complete','partial')) AS runs,
          (SELECT MAX(run_date) FROM snapshots s WHERE s.client_id=c.id AND s.status IN ('complete','partial')) AS last_run
        FROM clients c WHERE c.active=1 ORDER BY c.name
    """).fetchall()
    conn.close()
    return render_template_string(INDEX_HTML, clients=clients, models=AVAILABLE_MODELS, current=current_model())

INDEX_HTML = """
<!doctype html><html><head><title>SEO Agent</title>
<style>
  body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:40px}
  h1{color:#fff;font-size:28px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-top:24px}
  .card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px;text-decoration:none;color:inherit;transition:.15s}
  .card:hover{border-color:#2563eb;transform:translateY(-2px)}
  .card h2{margin:0 0 6px;font-size:18px;color:#fff}
  .card .domain{color:#60a5fa;font-size:14px}
  .card .meta{color:#94a3b8;font-size:13px;margin-top:10px}
</style></head><body>
  <h1>SEO Agent — Projects</h1>
  <a href="/add" style="display:inline-block;background:#2563eb;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;margin-bottom:8px">+ Add Project</a>
  <form method="post" action="/set-model" style="display:inline-block;margin-left:16px">
    <label style="font-size:13px;color:#94a3b8;margin-right:6px">AI model:</label>
    <select name="model" onchange="this.form.submit()" style="padding:8px 12px;border-radius:8px;background:#1e293b;color:#fff;border:1px solid #334155;font-size:14px">
      {% for val,label in models %}<option value="{{val}}" {{'selected' if val==current else ''}}>{{label}}</option>{% endfor %}
    </select>
  </form>
  <div class="grid">
    {% for c in clients %}
    <a class="card" href="/project/{{c.id}}">
      <h2>{{c.name}}</h2>
      <div class="domain">{{c.domain}}</div>
      <div class="meta">{{c.location}} · {{c.runs}} run(s)<br>Last: {{c.last_run or 'never'}}</div>
    </a>
    {% endfor %}
  </div>
</body></html>
"""



@app.route("/project/<int:cid>")
def project(cid):
    conn = db()
    client = conn.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
    snaps = conn.execute("SELECT id, run_date, status FROM snapshots WHERE client_id=? AND status IN ('complete','partial') ORDER BY run_date DESC", (cid,)).fetchall()
    trend = trends.compute_trends(conn, cid)
    # latest report file if it exists
    report = None
    if snaps:
        latest = snaps[0]["id"]
        fname = os.path.join(analyze.REPORTS, f"{client['name'].replace(' ','_')}_snapshot{latest}.md")
        if os.path.exists(fname):
            report = open(fname).read()
    conn.close()
    return render_template_string(PROJECT_HTML, client=client, snaps=snaps, trend=trend, report=report)

PROJECT_HTML = """
<!doctype html><html><head><title>{{client.name}} — SEO Agent</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
  body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;margin:0 auto;padding:40px;max-width:860px;line-height:1.5}
  a{color:#60a5fa}
  h1{color:#fff}
  .back{font-size:14px}
  .section{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:20px;margin:20px 0}
  .section h2{margin-top:0;font-size:18px;color:#fff}
  .metric{display:inline-block;margin:8px 20px 8px 0}
  .metric .val{font-size:22px;font-weight:600;color:#fff}
  .metric .lbl{font-size:12px;color:#94a3b8}
  .up{color:#4ade80}.down{color:#f87171}
  .report{font-size:15px;line-height:1.7;color:#cbd5e1}
  .report h1{font-size:22px;color:#fff;border-bottom:2px solid #2563eb;padding-bottom:6px}
  .report h2{font-size:17px;color:#93c5fd;margin-top:22px}
  .report strong{color:#fff}
  .report ul,.report ol{padding-left:22px}
  .report li{margin:5px 0}
  .report table{width:100%;border-collapse:collapse;margin:12px 0}
  .report th,.report td{border:1px solid #334155;padding:8px;text-align:left;font-size:14px}
  .report th{background:#1e293b;color:#fff}
  #chatbox{height:300px;overflow-y:auto;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:12px;margin-bottom:12px}
  .msg{margin:12px 0;padding:14px 18px;border-radius:14px;max-width:85%}
  .msg.user{background:#2563eb;color:#fff;margin-left:auto;border-bottom-right-radius:4px}
  .msg.bot{background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-bottom-left-radius:4px}
  input#q{flex:1;padding:14px;border-radius:10px;border:1px solid #334155;background:#0f172a;color:#fff;font-size:15px}
  .msg.bot{line-height:1.65;font-size:15px}
  .msg.bot h1,.msg.bot h2,.msg.bot h3{font-size:16px;margin:12px 0 6px;color:#fff}
  .msg.bot ul,.msg.bot ol{margin:8px 0;padding-left:20px}
  .msg.bot li{margin:4px 0}
  .msg.bot strong{color:#fff}
  .msg.bot p{margin:8px 0}
  .inputrow{display:flex;gap:10px;align-items:center}
  .typing{display:inline-flex;gap:4px;padding:4px 0}
  .typing span{width:8px;height:8px;background:#94a3b8;border-radius:50%;animation:blink 1.4s infinite both}
  .typing span:nth-child(2){animation-delay:.2s}
  .typing span:nth-child(3){animation-delay:.4s}
  @keyframes blink{0%,80%,100%{opacity:.2}40%{opacity:1}}
  button{padding:10px 18px;border:none;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer}
</style></head><body>
  <a class="back" href="/">← All projects</a>
  <h1>{{client.name}}</h1>
  <div><a href="https://{{client.domain}}" target="_blank">{{client.domain}}</a> · {{client.location}}</div>

  {% if trend %}
  <div class="section">
    <h2>Trend (vs previous run)</h2>
    <div class="metric"><div class="val {{'up' if trend.traffic.change_pct and trend.traffic.change_pct>0 else 'down'}}">{{trend.traffic.sessions_now}}</div><div class="lbl">Sessions ({{trend.traffic.change_pct}}%)</div></div>
    <div class="metric"><div class="val {{'up' if trend.search.clicks_change_pct and trend.search.clicks_change_pct>0 else 'down'}}">{{trend.search.clicks_now}}</div><div class="lbl">Clicks ({{trend.search.clicks_change_pct}}%)</div></div>
    <div class="metric"><div class="val">{{trend.search.impressions_now}}</div><div class="lbl">Impressions ({{trend.search.impressions_change_pct}}%)</div></div>
    <div class="metric"><div class="val">{{trend.search.avg_position_now}}</div><div class="lbl">Avg position</div></div>
    <div class="metric"><div class="val">{{trend.technical.issues_now}}</div><div class="lbl">Issues (was {{trend.technical.issues_prev}})</div></div>
  </div>
  {% else %}
  <div class="section"><h2>Trend</h2><p>Baseline snapshot — trends appear after the next run.</p></div>
  {% endif %}

  <div class="section">
    <h2>Chat with this project's data</h2>
    <div id="chatbox"></div>
    <div class="inputrow">
      <input id="q" placeholder="Ask about this client's SEO data..." onkeydown="if(event.key==='Enter')send()">
      <button onclick="send()">Send</button>
    </div>
  </div>

  {% if report %}
  <div class="section">
    <h2>Latest Report</h2>
    <div style="margin-bottom:14px"><a href="/export/{{client.id}}/report" style="background:#334155;color:#fff;padding:8px 14px;border-radius:8px;text-decoration:none;margin-right:8px;font-size:14px">↓ Download Report</a><a href="/export/{{client.id}}/data" style="background:#334155;color:#fff;padding:8px 14px;border-radius:8px;text-decoration:none;font-size:14px">↓ Download Raw Data</a></div>
    <div class="report" id="reportbox" data-md="{{ report|e }}"></div>
  </div>
  {% endif %}

<script>
const cid = {{client.id}};
function add(role,text){const b=document.getElementById('chatbox');const d=document.createElement('div');d.className='msg '+role;if(role==='user'){d.textContent=text;}else{d.innerHTML=marked.parse(text);}b.appendChild(d);b.scrollTop=b.scrollHeight;return d;}
async function send(){
  const i=document.getElementById('q');const q=i.value.trim();if(!q)return;
  add('user',q);i.value='';
  const b=document.getElementById('chatbox');
  const load=document.createElement('div');load.className='msg bot';load.innerHTML='<div class=\"typing\"><span></span><span></span><span></span></div>';b.appendChild(load);b.scrollTop=b.scrollHeight;
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cid:cid,q:q})});
    const d=await r.json();
    load.innerHTML=marked.parse(d.answer||d.error||'(no response)');
  }catch(e){load.textContent='Error: '+e;}
  b.scrollTop=b.scrollHeight;
}

// Render the latest report markdown
const rb=document.getElementById('reportbox');
if(rb){rb.innerHTML=marked.parse(rb.dataset.md||'');}
</script>
</body></html>
"""

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    cid = int(data["cid"])
    question = data["q"]
    conn = db()
    # Find latest snapshot for this client
    snap = conn.execute("SELECT id FROM snapshots WHERE client_id=? AND status IN ('complete','partial') ORDER BY run_date DESC LIMIT 1", (cid,)).fetchone()
    if not snap:
        conn.close()
        return jsonify({"error": "No data for this project yet."})
    brief = analyze.build_brief(conn, cid, snap["id"])
    conn.close()

    system = ("You are an SEO analyst answering questions about a specific client's SEO data. "
              "Use ONLY the data brief provided. Be concise and specific, cite the actual numbers. "
              "If the answer isn't in the data, say so. Ignore spam/irrelevant queries in the data.")
    payload = {
        "model": current_model(),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Client data brief:\n{json.dumps(brief)}\n\nQuestion: {question}"},
        ],
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    try:
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=120)
        r.raise_for_status()
        answer = r.json()["choices"][0]["message"]["content"]
        return jsonify({"answer": answer})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/add", methods=["GET", "POST"])
def add_project():
    if request.method == "POST":
        conn = db()
        conn.execute(
            "INSERT INTO clients (name, domain, ga4_property_id, gsc_site_url, location, business_context, active) VALUES (?,?,?,?,?,?,1)",
            (request.form["name"], request.form["domain"], request.form["ga4"],
             request.form["gsc"], request.form["location"], request.form.get("context",""))
        )
        conn.commit()
        conn.close()
        return ("<script>window.location='/'</script>")
    return render_template_string(ADD_HTML)

ADD_HTML = """
<!doctype html><html><head><title>Add Project — SEO Agent</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  body{font-family:'Inter',-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;margin:0 auto;padding:40px;max-width:600px}
  a{color:#60a5fa}h1{color:#fff}
  label{display:block;margin:16px 0 4px;font-size:14px;color:#94a3b8}
  input,textarea{width:100%;padding:12px;border-radius:8px;border:1px solid #334155;background:#1e293b;color:#fff;font-size:15px;box-sizing:border-box;font-family:inherit}
  .hint{font-size:12px;color:#64748b;margin-top:2px}
  button{margin-top:24px;padding:12px 24px;border:none;border-radius:8px;background:#2563eb;color:#fff;font-size:15px;cursor:pointer}
</style></head><body>
  <a href="/">← All projects</a>
  <h1>Add a Project</h1>
  <form method="post">
    <label>Client name</label><input name="name" required placeholder="Acme Ltd">
    <label>Domain</label><input name="domain" required placeholder="acme.com">
    <div class="hint">No https:// — just the domain</div>
    <label>GA4 Property ID</label><input name="ga4" placeholder="381960609">
    <div class="hint">GA4 Admin → Property Settings (numeric)</div>
    <label>GSC Site URL</label><input name="gsc" placeholder="sc-domain:acme.com">
    <div class="hint">Domain properties use the sc-domain: prefix</div>
    <label>Location</label><input name="location" value="United States" required>
    <div class="hint">Country for keyword search volume (e.g. United Kingdom, India)</div>
    <label>Business context (optional)</label><textarea name="context" rows="3" placeholder="What the business does — helps the AI judge which keywords are relevant"></textarea>
    <button type="submit">Add Project</button>
  </form>
</body></html>
"""



@app.route("/export/<int:cid>/report")
def export_report(cid):
    from flask import Response
    conn = db()
    client = conn.execute("SELECT name FROM clients WHERE id=?", (cid,)).fetchone()
    snap = conn.execute("SELECT id FROM snapshots WHERE client_id=? AND status IN ('complete','partial') ORDER BY run_date DESC LIMIT 1", (cid,)).fetchone()
    conn.close()
    if not snap:
        return "No report yet", 404
    fname = os.path.join(analyze.REPORTS, f"{client['name'].replace(' ','_')}_snapshot{snap['id']}.md")
    if not os.path.exists(fname):
        return "No report file", 404
    return Response(open(fname).read(), mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={client['name'].replace(' ','_')}_report.md"})

@app.route("/export/<int:cid>/data")
def export_data(cid):
    from flask import Response
    conn = db()
    client = conn.execute("SELECT name FROM clients WHERE id=?", (cid,)).fetchone()
    snap = conn.execute("SELECT id FROM snapshots WHERE client_id=? AND status IN ('complete','partial') ORDER BY run_date DESC LIMIT 1", (cid,)).fetchone()
    if not snap:
        conn.close(); return "No data yet", 404
    sid = snap["id"]
    out = {"crawl_issues": [dict(r) for r in conn.execute("SELECT url,issue,issue_type,category,details FROM crawl_issues WHERE snapshot_id=?", (sid,)).fetchall()],
           "ga4": [dict(r) for r in conn.execute("SELECT metric_name,metric_value,dimension,period_start,period_end FROM ga4_metrics WHERE snapshot_id=?", (sid,)).fetchall()],
           "gsc": [dict(r) for r in conn.execute("SELECT query,clicks,impressions,ctr,position FROM gsc_metrics WHERE snapshot_id=?", (sid,)).fetchall()],
           "rankings": [dict(r) for r in conn.execute("SELECT keyword,search_volume,location FROM rankings WHERE snapshot_id=?", (sid,)).fetchall()]}
    conn.close()
    return Response(json.dumps(out, indent=2), mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={client['name'].replace(' ','_')}_data.json"})



@app.route("/set-model", methods=["POST"])
def set_model():
    m = request.form["model"]
    conn = db()
    conn.execute("INSERT INTO settings (key,value) VALUES ('model',?) ON CONFLICT(key) DO UPDATE SET value=?", (m, m))
    conn.commit()
    conn.close()
    return ("<script>window.location='/'</script>")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
