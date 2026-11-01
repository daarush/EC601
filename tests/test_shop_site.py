"""Ground-truth tests for Site C ("shop"). If one of these changes, the target has changed and every
result collected on it must be re-collected, so a failing test here is a feature, not an annoyance."""
import importlib.util
import json
from pathlib import Path

import pytest

from fuzzer.targets import TARGETS

_APP = Path(__file__).resolve().parent.parent / "targets" / "shop_site" / "app.py"
_spec = importlib.util.spec_from_file_location("shop_site_app", _APP)
shop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shop)

SEED = dict(TARGETS["shop"]["seed_request"])


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(shop, "LOG_FILE", tmp_path / "server_log.jsonl")
    shop.LOG_FILE.write_text("")
    return shop.app.test_client()


def send(client, **overrides):
    payload = {**SEED, **overrides}
    payload = {k: v for k, v in payload.items() if v is not ...}      # `...` = drop the field
    resp = client.post("/checkout", json=payload)
    entry = next(e for e in client.get("/logs").get_json()["entries"]
                 if e["correlation_id"] == resp.headers["X-Correlation-ID"])
    return resp, entry


def outcome(client, **overrides):
    resp, entry = send(client, **overrides)
    return resp.status_code, entry["outcome"]


# ------------------------------------------------------------------ the seed request and the registry
def test_seed_request_is_a_valid_order(client):
    resp, entry = send(client)
    assert resp.status_code == 200 and entry["outcome"] == "order_ok" and entry["sink_reached"] is True


def test_target_is_registered_with_the_site_contract():
    t = TARGETS["shop"]
    assert t["url"].endswith(":5002/checkout") and t["kind"] == "json" and t["logs_url"] and t["reset_url"]
    assert set(t["seed_request"]) == {"email", "country", "postal_code", "quantity", "shipping", "coupon", "note", "sig"}


# ------------------------------------------------------------------ validation chain (one outcome each)
@pytest.mark.parametrize("overrides, expected", [
    (dict(postal_code=...), (400, "missing_fields")),
    (dict(quantity=2), (400, "bad_type")),
    (dict(email="alice"), (400, "bad_email")),
    (dict(country="FR"), (400, "bad_country")),
    (dict(postal_code="ABCDE"), (400, "bad_postal")),
    (dict(quantity="100"), (400, "bad_quantity")),
    (dict(quantity="0"), (400, "bad_quantity")),
    (dict(shipping="teleport"), (400, "bad_shipping")),
    (dict(coupon="save10"), (400, "bad_coupon")),
    (dict(coupon="VIP20"), (404, "unknown_coupon")),
    (dict(coupon="SAVE99"), (400, "coupon_out_of_range")),
    (dict(note="x" * 201), (400, "note_too_long")),
    (dict(sig="deadbeef"), (403, "bad_signature")),
])
def test_each_validation_stage_has_its_own_outcome(client, overrides, expected):
    assert outcome(client, **overrides) == expected


def test_postal_code_format_depends_on_country(client):
    assert outcome(client, country="GB", postal_code="02215") == (400, "bad_postal")      # US format, GB country
    assert outcome(client, country="GB", postal_code="SW1A 1AA") == (200, "order_ok")
    assert outcome(client, country="DE", postal_code="10115") == (200, "order_ok")
    assert outcome(client, country="US", postal_code="SW1A 1AA") == (400, "bad_postal")


def test_valid_coupon_and_express_shipping_work(client):
    assert outcome(client, coupon="SAVE10") == (200, "order_ok")
    assert outcome(client, shipping="express", quantity="9") == (200, "order_ok")


# ------------------------------------------------------------------ the planted bugs
def test_coupon_parser_crash_needs_save_without_digits(client):
    for coupon in ("SAVE", "SAVEX"):
        status, out = outcome(client, coupon=coupon)
        assert (status, out) == (500, "coupon_parser_crash")
    resp, _ = send(client, coupon="SAVE")
    assert "ValueError" in resp.get_json()["error"]


def test_express_zero_division_needs_express_and_quantity_ten(client):
    assert outcome(client, shipping="express", quantity="10") == (500, "express_zero_division")
    assert outcome(client, shipping="standard", quantity="10") == (200, "order_ok")
    assert outcome(client, shipping="express", quantity="11") == (200, "order_ok")


def test_sql_injection_through_note_and_email(client):
    resp, entry = send(client, note="it's")
    assert (resp.status_code, entry["outcome"], entry["sink_reached"]) == (500, "sqli_error", True)
    assert "sqlite3" in resp.get_json()["error"]
    assert outcome(client, email="o'brien@example.com") == (500, "sqli_error")


def test_premium_crash_is_unreachable_without_the_secret(client):
    """Tripwire: only a valid HMAC reaches this bug. Black-box strategies must never trigger it."""
    good = shop.expected_signature(SEED["email"], int(SEED["quantity"]))
    assert outcome(client, sig=good) == (500, "premium_crash")
    for guess in ("", "00000000", "SAVE", "a" * 8, SEED["email"], "\ud800"):
        assert outcome(client, sig=guess)[1] != "premium_crash"


# ------------------------------------------------------------------ ground-truth logging
def test_depth_increases_along_the_chain(client):
    depths = {name: send(client, **ov)[1]["depth"] for name, ov in [
        ("missing", dict(postal_code=...)), ("email", dict(email="x")), ("country", dict(country="FR")),
        ("postal", dict(postal_code="ABCDE")), ("quantity", dict(quantity="0")), ("shipping", dict(shipping="x")),
        ("coupon", dict(coupon="save")), ("note", dict(note="x" * 201)), ("ok", dict())]}
    order = ["missing", "email", "country", "postal", "quantity", "shipping", "coupon", "note", "ok"]
    assert [depths[k] for k in order] == sorted(depths[k] for k in order)
    assert len(set(depths.values())) == len(depths)            # every stage is a distinct depth


def test_every_request_is_logged_even_for_type_confusion(client):
    for value in (None, 0, 1, True, [], {}, 3.14, "\x00", "😀" * 50, "a" * 5000):
        for field in SEED:
            resp, entry = send(client, **{field: value})
            assert entry["outcome"] != "unexpected_exception", (field, value)


def test_non_object_and_malformed_bodies(client):
    assert client.post("/checkout", data="not json", content_type="application/json").status_code == 400
    assert client.post("/checkout", json=[1, 2]).status_code == 400
    outcomes = [e["outcome"] for e in client.get("/logs").get_json()["entries"]]
    assert outcomes == ["malformed_json", "not_object"]


def test_reset_clears_the_log(client):
    send(client)
    assert client.get("/logs").get_json()["count"] == 1
    client.post("/reset")
    assert client.get("/logs").get_json()["count"] == 0
    assert shop.LOG_FILE.read_text() == ""
