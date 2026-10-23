import json

import httpx

from fuzzer.core import BaselineStrategy, run, save, summarize


def _rec():
    return [{"i": 0, "status": 400, "interesting": False, "depth": 1, "sink_reached": False}]


def test_save_without_wordlist_keeps_legacy_name(tmp_path):
    p = save(_rec(), "t", "baseline", 42, 5, out_dir=tmp_path)
    assert p.name == "run_t_baseline_s42_b5.json"
    assert "wordlist" not in json.loads(p.read_text())["meta"]


def test_save_records_wordlist_in_meta_and_filename(tmp_path):
    p = save(_rec(), "t", "baseline", 42, 5, wordlist="informed", out_dir=tmp_path)
    assert p.name == "run_t_baseline_informed_s42_b5.json"
    assert json.loads(p.read_text())["meta"]["wordlist"] == "informed"


def test_same_run_different_wordlist_does_not_overwrite(tmp_path):
    a = save(_rec(), "t", "baseline", 42, 5, wordlist="mini", out_dir=tmp_path)
    b = save(_rec(), "t", "baseline", 42, 5, wordlist="informed", out_dir=tmp_path)
    assert a != b and a.exists() and b.exists()


def test_save_creates_out_dir(tmp_path):
    p = save(_rec(), "t", "baseline", 1, 1, out_dir=tmp_path / "nested" / "dir")
    assert p.exists()


# --- server-side outcome is recorded (ground truth for the outcome-coverage metric) ---

def _client_with_outcomes(outcomes):
    state = {"n": 0}

    def handler(req):
        if req.url.path == "/logs":
            entries = [{"correlation_id": f"c{i}", "depth": 1, "sink_reached": False, "outcome": o}
                       for i, o in enumerate(outcomes)]
            return httpx.Response(200, json={"entries": entries})
        i = state["n"]
        state["n"] += 1
        return httpx.Response(200, json={}, headers={"X-Correlation-ID": f"c{i}"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_outcome_is_joined_and_distinct_outcomes_counted():
    target = {"url": "http://test/x", "kind": "json", "logs_url": "http://test/logs"}
    recs = run(target, BaselineStrategy({"a": "b"}, [], 1), 4, client=_client_with_outcomes(["x", "y", "x", "z"]))
    assert [r["outcome"] for r in recs] == ["x", "y", "x", "z"]
    assert summarize(recs)["distinct_outcomes"] == 3


def test_distinct_outcomes_is_zero_without_a_server_log():
    target = {"url": "http://test/x", "kind": "json"}
    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={}, headers={"X-Correlation-ID": "x"})))
    recs = run(target, BaselineStrategy({"a": "b"}, [], 1), 3, client=client)
    assert summarize(recs)["distinct_outcomes"] == 0
