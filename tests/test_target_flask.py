import json
import pytest
import targets.flask_app.app as t

GOOD = {"username": "alice@example.com", "query": "SEARCH:hello world"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "LOG_FILE", tmp_path / "log.jsonl")  # never touch the real log
    return t.app.test_client()


def last_log(tmp_path):
    return json.loads((tmp_path / "log.jsonl").read_text().splitlines()[-1])


@pytest.mark.parametrize("payload,status,outcome", [
    ({**GOOD, "username": "not_an_email"},           400, "bad_email_format"),
    ({**GOOD, "username": "root@example.com"},       403, "blacklisted_user"),
    ({**GOOD, "username": "abcd@example.com"},       400, "bad_username_length"),
    ({**GOOD, "query": "short"},                     400, "query_too_short"),
    ({**GOOD, "query": "<script>alert(1)</script>"}, 403, "waf_blocked"),
    ({**GOOD, "query": "no prefix here at all"},     400, "no_sink_prefix"),
    ({**GOOD, "query": "SEARCH:it's broken"},        500, "sql_error"),
    (GOOD,                                           200, "sink_executed"),
])
def test_stage_outcomes(client, tmp_path, payload, status, outcome):
    r = client.post("/submit", json=payload)
    assert r.status_code == status
    assert last_log(tmp_path)["outcome"] == outcome


def test_malformed_json(client, tmp_path):
    r = client.post("/submit", data="{nope", content_type="application/json")
    assert r.status_code == 400
    assert last_log(tmp_path)["outcome"] == "malformed_json"


def test_non_object_json(client, tmp_path):
    r = client.post("/submit", json=[1, 2, 3])
    assert r.status_code == 400
    assert last_log(tmp_path)["outcome"] == "not_object"


def test_missing_field(client, tmp_path):
    r = client.post("/submit", json={"username": "alice@example.com"})
    assert r.status_code == 400
    assert last_log(tmp_path)["outcome"] == "missing_fields"


def test_type_confusion_username(client, tmp_path):
    r = client.post("/submit", json={**GOOD, "username": 123})
    assert r.status_code == 400
    assert last_log(tmp_path)["outcome"] == "bad_email_format"


def test_correlation_id_matches_log(client, tmp_path):
    r = client.post("/submit", json=GOOD)
    assert r.headers["X-Correlation-ID"] == last_log(tmp_path)["correlation_id"]


def test_depth_increases_with_progress(client, tmp_path):
    client.post("/submit", json={**GOOD, "username": "bad"})
    shallow = last_log(tmp_path)["depth"]
    client.post("/submit", json=GOOD)
    deep = last_log(tmp_path)
    assert deep["depth"] > shallow
    assert deep["sink_reached"] is True


def test_reset_clears_log(client):
    client.post("/submit", json=GOOD)
    client.post("/reset")
    assert client.get("/logs").get_json()["count"] == 0