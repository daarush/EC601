"""
Site C ("shop"): a small checkout API for the EC 601 web-fuzzing project.

Why it exists
-------------
Sites A and B leave almost no headroom: A is capped by the mutator, B's bug is found by the baseline in ~65
requests. Site C is a realistic-looking order endpoint with a deep, *dependent* validation chain and several
planted bugs at different depths, so a better strategy has something to find. Ground truth is known exactly
(every response is logged server-side with a stage list and an outcome label), which a real-world app would not give us.

Design rules (frozen once the baseline has been calibrated; see docs/SITE_C.md)
-----------------------------------------------------------------------------
* Black box: strategies only ever see status code and body. Stages, depth and outcome live in server_log.jsonl.
* Every rejection has a distinct, realistic message (a human tester would read them).
* One field depends on another (postal_code format depends on country).
* Bugs, by depth:
    - coupon_parser_crash   (500, ValueError)        coupon "SAVE" + no digits
    - express_zero_division (500, ZeroDivisionError) shipping "express" AND quantity 10
    - sqli_error            (500, sqlite3 error)     a quote in `note` or `email` reaches an INSERT built by string concat
    - premium_crash         (500, KeyError)          needs a valid HMAC `sig`; NOT reachable by black-box guessing.
                                                      It is a TRIPWIRE: if any strategy triggers it, something leaks.
* The only inputs are the 8 JSON fields of the seed request; no strategy can add new fields.

Endpoints: POST /checkout, GET /logs, POST /reset, GET /.
"""

import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, g, jsonify, request

app = Flask(__name__)

# --- Configuration ---------------------------------------------------------

LOG_FILE = Path(__file__).parent / "server_log.jsonl"
SECRET = b"shop-site-signing-secret-that-is-in-no-wordlist"
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
POSTAL_BY_COUNTRY = {
    "US": re.compile(r"^\d{5}(-\d{4})?$"),
    "GB": re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}$"),
    "DE": re.compile(r"^\d{5}$"),
}
QUANTITY_REGEX = re.compile(r"^[0-9]{1,2}$")
COUPON_FORMAT = re.compile(r"^[A-Z]{2,8}[0-9]*$")
SHIPPING = {"standard", "express"}
REQUIRED = ("email", "country", "postal_code", "quantity", "shipping")
OPTIONAL = ("coupon", "note", "sig")

DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, email TEXT, note TEXT, qty INTEGER)")

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


def respond(body: dict, status: int, cid: str) -> Response:
    resp = jsonify(body)
    resp.status_code = status
    resp.headers["X-Correlation-ID"] = cid
    return resp


def reject(cid, passed, outcome, msg, status):
    log_event(cid, passed, False, outcome)
    return respond({"error": msg}, status, cid)


def crash(cid, passed, outcome, exc, sink_reached=False):
    """What a leaky production API does with an exception: HTTP 500 with the exception text."""
    log_event(cid, passed, sink_reached, outcome)
    module = type(exc).__module__
    name = type(exc).__name__ if module == "builtins" else f"{module}.{type(exc).__name__}"
    return respond({"error": f"{name}: {exc}"}, 500, cid)


@app.errorhandler(Exception)
def unexpected(exc):
    """Safety net so every request is logged. Any 'unexpected_exception' is an unplanned bug in this file."""
    cid = getattr(g, "cid", str(uuid.uuid4()))
    log_event(cid, getattr(g, "passed", []), False, "unexpected_exception")
    return respond({"error": f"{type(exc).__name__}: {exc}"}, 500, cid)

# --- Target endpoints ------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "endpoints": ["/checkout"]})


def expected_signature(email: str, qty: int) -> str:
    return hmac.new(SECRET, f"{email}|{qty}".encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()[:8]


@app.route("/checkout", methods=["POST"])
def checkout():
    cid, passed = str(uuid.uuid4()), []
    g.cid, g.passed = cid, passed

    try:
        data = request.get_json(force=True)
    except Exception:
        return reject(cid, passed, "malformed_json", "Body must be valid JSON", 400)
    if not isinstance(data, dict):
        return reject(cid, passed, "not_object", "Body must be a JSON object", 400)
    passed.append("json_ok")

    if any(data.get(k) is None for k in REQUIRED):
        return reject(cid, passed, "missing_fields",
                      "Required fields: email, country, postal_code, quantity, shipping", 400)
    passed.append("presence_ok")

    if any(data.get(k) is not None and not isinstance(data.get(k), str) for k in REQUIRED + OPTIONAL):
        return reject(cid, passed, "bad_type", "All fields must be strings", 400)
    passed.append("type_ok")

    email, country, postal = data["email"], data["country"], data["postal_code"]
    quantity, shipping = data["quantity"], data["shipping"]
    coupon, note, sig = data.get("coupon") or "", data.get("note") or "", data.get("sig") or ""

    if not EMAIL_REGEX.match(email):
        return reject(cid, passed, "bad_email", "'email' must be a valid address like user@domain.tld", 400)
    passed.append("email_ok")

    if country not in POSTAL_BY_COUNTRY:
        return reject(cid, passed, "bad_country", "Unsupported destination country", 400)
    passed.append("country_ok")

    if not POSTAL_BY_COUNTRY[country].match(postal):
        return reject(cid, passed, "bad_postal", f"Postal code does not match the format for {country}", 400)
    passed.append("postal_ok")

    if not QUANTITY_REGEX.match(quantity) or not 1 <= int(quantity) <= 99:
        return reject(cid, passed, "bad_quantity", "'quantity' must be an integer from 1 to 99", 400)
    qty = int(quantity)
    passed.append("quantity_ok")

    if shipping not in SHIPPING:
        return reject(cid, passed, "bad_shipping", "'shipping' must be 'standard' or 'express'", 400)
    passed.append("shipping_ok")

    if coupon:
        if not COUPON_FORMAT.match(coupon):
            return reject(cid, passed, "bad_coupon", "Invalid coupon format (example: SAVE10)", 400)
        if not coupon.startswith("SAVE"):
            return reject(cid, passed, "unknown_coupon", "Coupon not found", 404)
        try:
            pct = int(coupon[4:])                   # BUG: "SAVE" with no digits is never rejected before this line
        except ValueError as exc:
            return crash(cid, passed, "coupon_parser_crash", exc)
        if not 1 <= pct <= 50:
            return reject(cid, passed, "coupon_out_of_range", "Coupon discount out of range", 400)
    passed.append("coupon_ok")

    if shipping == "express":
        try:
            express_slots = 20 // (10 - qty)        # BUG: quantity 10 divides by zero
        except ZeroDivisionError as exc:
            return crash(cid, passed, "express_zero_division", exc)
    passed.append("delivery_ok")

    if sig:
        if not hmac.compare_digest(sig.encode("utf-8", "surrogatepass"),
                                   expected_signature(email, qty).encode()):
            return reject(cid, passed, "bad_signature", "Invalid request signature", 403)
        passed.append("sig_ok")
        try:
            premium_tier = {}["tier"]                # BUG behind the signature: unreachable without the secret
        except KeyError as exc:
            return crash(cid, passed, "premium_crash", exc)

    if len(note) > 200:
        return reject(cid, passed, "note_too_long", "'note' must be at most 200 characters", 400)
    passed.append("note_ok")

    passed.append("sink_reached")
    try:                                              # BUG: SQL built by string concatenation
        DB.execute(f"INSERT INTO orders(email, note, qty) VALUES ('{email}', '{note}', {qty})")
        DB.commit()
    except sqlite3.Error as exc:
        return crash(cid, passed, "sqli_error", exc, sink_reached=True)
    log_event(cid, passed, True, "order_ok")
    return respond({"status": "ok", "order": "created"}, 200, cid)

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
    app.run(host="127.0.0.1", port=5002, debug=False)
