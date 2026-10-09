import json
import pytest
import targets.vuln_site.app as t


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "LOG_FILE", tmp_path / "log.jsonl")
    return t.app.test_client()


def last_log(tmp_path):
    return json.loads((tmp_path / "log.jsonl").read_text().splitlines()[-1])


def test_normal_search(client):
    r = client.get("/search?q=widget")
    assert r.status_code == 200
    assert r.get_json()["rows"][0][1] == "widget"


def test_missing_q(client, tmp_path):
    assert client.get("/search").status_code == 400
    assert last_log(tmp_path)["outcome"] == "missing_q"


def test_bad_limit(client, tmp_path):
    assert client.get("/search?q=a&limit=abc").status_code == 400
    assert last_log(tmp_path)["outcome"] == "bad_limit"


def test_quote_causes_500_with_signature(client):
    r = client.get("/search", query_string={"q": "'"})
    assert r.status_code == 500
    assert "sqlite3." in r.get_json()["error"]


def test_union_injection_is_real(client):
    r = client.get("/search", query_string={"q": "zzz' UNION SELECT 1,2,3 --"})
    assert r.status_code == 200
    assert r.get_json()["rows"] == [[1, 2, 3]]


def test_log_depth_and_cid(client, tmp_path):
    r = client.get("/search?q=widget")
    entry = last_log(tmp_path)
    assert entry["correlation_id"] == r.headers["X-Correlation-ID"]
    assert entry["depth"] == 4 and entry["sink_reached"] is True