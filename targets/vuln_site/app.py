"""Site B: tiny SQLite-backed search with a REAL string-concat injection."""
import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify

app = Flask(__name__)
LOG_FILE = Path(__file__).parent / "server_log.jsonl"
CON = sqlite3.connect(":memory:", check_same_thread=False)
CON.executescript("""CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT, price REAL);
INSERT INTO items(name,price) VALUES ('widget',9.99),('gadget',19.5),('gizmo',4.25);""")

def reply(cid, passed, sink, outcome, body, status):
    with LOG_FILE.open("a") as f:
        f.write(json.dumps({"correlation_id": cid,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stages_passed": passed, "depth": len(passed),
            "sink_reached": sink, "outcome": outcome}) + "\n")
    resp = jsonify(body); resp.status_code = status
    resp.headers["X-Correlation-ID"] = cid
    return resp

@app.get("/search")
def search():
    cid, passed = str(uuid.uuid4()), []
    q, limit = request.args.get("q"), request.args.get("limit", "10")
    if q is None:
        return reply(cid, passed, False, "missing_q", {"error": "q required"}, 400)
    passed.append("q_present")
    if not limit.isdigit():
        return reply(cid, passed, False, "bad_limit", {"error": "limit must be an integer"}, 400)
    passed.append("limit_ok")
    sql = f"SELECT id,name,price FROM items WHERE name LIKE '%{q}%' LIMIT {limit}"
    passed.append("sql_attempted")
    try:
        rows = CON.execute(sql).fetchall()
    except sqlite3.Error as e:
        return reply(cid, passed, True, "sql_error",
                     {"error": f"sqlite3.{type(e).__name__}: {e}"}, 500)
    passed.append("sql_ok")
    return reply(cid, passed, True, "ok", {"rows": rows}, 200)

@app.get("/logs")
def logs():
    lines = LOG_FILE.read_text().splitlines() if LOG_FILE.exists() else []
    return jsonify({"entries": [json.loads(l) for l in lines if l]})

@app.post("/reset")
def reset():
    LOG_FILE.write_text("")
    return jsonify({"status": "reset"})

if __name__ == "__main__":
    LOG_FILE.write_text("")
    app.run(host="127.0.0.1", port=5001, debug=False)