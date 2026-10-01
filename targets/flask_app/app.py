"""
Instrumented Flask target for EC 601 web fuzzing project.

Design rationale:
- 7 validation stages, each with a DISTINCT error message. This gives the
  fuzzer (and the LLM variant) a learnable signal about what's required.
- A "sink" is only reachable after passing ALL stages. Random mutation
  almost never reaches it; a smart fuzzer might.
- Every request gets a correlation ID (UUID) returned in the response
  header AND logged server-side, so we can match fuzzer logs to
  server-side ground truth.
- Server-side log is written to `server_log.json` in this directory.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# --- Configuration ---------------------------------------------------------

LOG_FILE = Path(__file__).parent / "server_log.json"
BLACKLIST = {"admin", "root", "test", "superuser", "null", "undefined"}
BANNED_QUERY_TOKENS = {"DROP", "DELETE", "TRUNCATE", "EXEC", "<script"}
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SINK_PREFIX = "SEARCH:"

# --- Instrumentation -------------------------------------------------------

def log_event(correlation_id: str, stages_reached: list[str],
              sink_reached: bool, outcome: str) -> None:
    """Append one server-side event to the log file."""
    entry = {
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stages_reached": stages_reached,
        "sink_reached": sink_reached,
        "outcome": outcome,
    }
    # Append-line JSON (JSONL) — easy to grep, easy to stream.
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def make_response_with_cid(body: dict, status: int, correlation_id: str) -> Response:
    resp = jsonify(body)
    resp.status_code = status
    resp.headers["X-Correlation-ID"] = correlation_id
    return resp

# --- Target endpoint -------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "endpoints": ["/submit"]})


@app.route("/submit", methods=["POST"])
def submit():
    correlation_id = str(uuid.uuid4())
    stages_reached: list[str] = []
    sink_reached = False

    # Stage 1: Parse body
    try:
        data = request.get_json(force=True)
    except Exception:
        log_event(correlation_id, stages_reached, sink_reached, "malformed_json")
        return make_response_with_cid(
            {"error": "Request body must be valid JSON"}, 400, correlation_id
        )

    if not isinstance(data, dict):
        log_event(correlation_id, stages_reached, sink_reached, "not_object")
        return make_response_with_cid(
            {"error": "Request body must be a JSON object"}, 400, correlation_id
        )

    username = data.get("username")
    query = data.get("query")

    # Stage 2: Presence
    if not username or not query:
        stages_reached.append("presence_check")
        log_event(correlation_id, stages_reached, sink_reached, "missing_fields")
        return make_response_with_cid(
            {"error": "Both 'username' and 'query' fields are required"},
            400, correlation_id,
        )

    # Stage 3: Email format
    stages_reached.append("presence_check")
    if not isinstance(username, str) or not EMAIL_REGEX.match(username):
        log_event(correlation_id, stages_reached, sink_reached, "bad_email_format")
        return make_response_with_cid(
            {"error": "'username' must be a valid email address (user@domain.tld)"},
            400, correlation_id,
        )

    # Stage 4: Blacklist
    stages_reached.append("email_format_ok")
    if username.split("@")[0].lower() in BLACKLIST:
        log_event(correlation_id, stages_reached, sink_reached, "blacklisted_user")
        return make_response_with_cid(
            {"error": "This username is reserved"}, 403, correlation_id
        )

    # Stage 5: Length
    stages_reached.append("blacklist_ok")
    if not (5 <= len(username) <= 50):
        log_event(correlation_id, stages_reached, sink_reached, "bad_username_length")
        return make_response_with_cid(
            {"error": "'username' local part must be 5-50 characters"},
            400, correlation_id,
        )

    # Stage 6: Query length + banned tokens (simulated WAF)
    stages_reached.append("username_valid")
    if not isinstance(query, str) or len(query) < 10:
        log_event(correlation_id, stages_reached, sink_reached, "query_too_short")
        return make_response_with_cid(
            {"error": "'query' must be at least 10 characters"}, 400, correlation_id
        )
    if any(token in query.upper() for token in BANNED_QUERY_TOKENS):
        log_event(correlation_id, stages_reached, sink_reached, "waf_blocked")
        return make_response_with_cid(
            {"error": "Query blocked by security filter"}, 403, correlation_id
        )

    # Stage 7: Sink — requires magic prefix
    stages_reached.append("query_valid")
    if not query.startswith(SINK_PREFIX):
        log_event(correlation_id, stages_reached, sink_reached, "no_sink_prefix")
        return make_response_with_cid(
            {"error": "Query must begin with operation prefix"}, 400, correlation_id
        )

    # SINK REACHED
    sink_reached = True
    stages_reached.append("sink_reached")
    # Simulated SQL execution (just logged, never actually run).
    simulated_sql = f"SELECT * FROM users WHERE name='{username}' AND q='{query}'"
    log_event(correlation_id, stages_reached, sink_reached, "sink_executed")
    return make_response_with_cid(
        {"status": "ok", "executed": simulated_sql}, 200, correlation_id
    )

# --- Debug endpoint (for verification only) -------------------------------

@app.route("/logs", methods=["GET"])
def logs():
    """View the server-side log. Useful for verifying instrumentation."""
    if not LOG_FILE.exists():
        return jsonify({"entries": []})
    entries = [json.loads(line) for line in LOG_FILE.read_text().splitlines() if line]
    return jsonify({"entries": entries, "count": len(entries)})


@app.route("/reset", methods=["POST"])
def reset():
    """Clear the server-side log between experimental runs."""
    if LOG_FILE.exists():
        LOG_FILE.write_text("")
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    # Clear log on startup so each experimental run starts clean.
    LOG_FILE.write_text("")
    app.run(host="127.0.0.1", port=5000, debug=False)