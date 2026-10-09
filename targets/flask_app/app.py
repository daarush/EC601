"""
Instrumented Flask target (Site A) for EC 601 web fuzzing project.

Design rationale:
- Multi-stage validation chain; each rejection has a distinct message.
- Every request gets a correlation ID (UUID) returned in the
  X-Correlation-ID header AND logged server-side (ground truth).
- Log records only stages PASSED; depth = len(stages_passed).
- A deliberate bug behind all stages (a quote in the query) returns a 500,
  so the oracle's 5xx / error-signature rules can actually fire.
- Server-side log is JSONL: server_log.jsonl in this directory.

DESIGN DECISION (frozen): the stage-7 message hints at the format
("<OPERATION>:<argument>") but does not reveal the literal prefix.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

# --- Configuration ---------------------------------------------------------

LOG_FILE = Path(__file__).parent / "server_log.jsonl"
BLACKLIST = {"admin", "root", "test", "superuser", "null", "undefined"}
BANNED_QUERY_TOKENS = {"DROP", "DELETE", "TRUNCATE", "EXEC", "<SCRIPT"}  # uppercase!
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SINK_PREFIX = "SEARCH:"

# --- Instrumentation -------------------------------------------------------

def log_event(cid, passed, sink_reached, outcome):
    entry = {
        "correlation_id": cid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stages_passed": list(passed),
        "depth": len(passed),
        "sink_reached": sink_reached,
        "outcome": outcome,
    }
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def make_response_with_cid(body: dict, status: int, correlation_id: str) -> Response:
    resp = jsonify(body)
    resp.status_code = status
    resp.headers["X-Correlation-ID"] = correlation_id
    return resp


def reject(cid, passed, outcome, msg, status):
    log_event(cid, passed, False, outcome)
    return make_response_with_cid({"error": msg}, status, cid)

# --- Target endpoints ------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "endpoints": ["/submit"]})


@app.route("/submit", methods=["POST"])
def submit():
    cid, passed = str(uuid.uuid4()), []

    try:
        data = request.get_json(force=True)
    except Exception:
        return reject(cid, passed, "malformed_json", "Body must be valid JSON", 400)
    if not isinstance(data, dict):
        return reject(cid, passed, "not_object", "Body must be a JSON object", 400)
    passed.append("json_ok")

    username, query = data.get("username"), data.get("query")
    if not username or not query:
        return reject(cid, passed, "missing_fields", "'username' and 'query' required", 400)
    passed.append("presence_ok")

    if not isinstance(username, str) or not EMAIL_REGEX.match(username):
        return reject(cid, passed, "bad_email_format", "'username' must be user@domain.tld", 400)
    passed.append("email_ok")

    local = username.split("@")[0]
    if local.lower() in BLACKLIST:
        return reject(cid, passed, "blacklisted_user", "This username is reserved", 403)
    passed.append("blacklist_ok")

    if not (5 <= len(local) <= 50):
        return reject(cid, passed, "bad_username_length", "Local part must be 5-50 chars", 400)
    passed.append("length_ok")

    if not isinstance(query, str) or len(query) < 10:
        return reject(cid, passed, "query_too_short", "'query' must be >= 10 chars", 400)
    if any(tok in query.upper() for tok in BANNED_QUERY_TOKENS):
        return reject(cid, passed, "waf_blocked", "Query blocked by security filter", 403)
    passed.append("query_ok")

    if not query.startswith(SINK_PREFIX):
        return reject(cid, passed, "no_sink_prefix",
                      "Query must look like <OPERATION>:<argument>", 400)
    passed.append("prefix_ok")

    passed.append("sink_reached")
    if "'" in query:  # deliberate bug behind all stages -> gives the oracle a 5xx
        log_event(cid, passed, True, "sql_error")
        return make_response_with_cid(
            {"error": "sqlite3.OperationalError: unrecognized token"}, 500, cid)
    log_event(cid, passed, True, "sink_executed")
    return make_response_with_cid({"status": "ok"}, 200, cid)

# --- Debug endpoints (verification / experiment control) -------------------

@app.route("/logs", methods=["GET"])
def logs():
    if not LOG_FILE.exists():
        return jsonify({"entries": [], "count": 0})
    entries = [json.loads(line) for line in LOG_FILE.read_text().splitlines() if line]
    return jsonify({"entries": entries, "count": len(entries)})


@app.route("/reset", methods=["POST"])
def reset():
    LOG_FILE.write_text("")
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    LOG_FILE.write_text("")  # clean log on startup
    app.run(host="127.0.0.1", port=5000, debug=False)