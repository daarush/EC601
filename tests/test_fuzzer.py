import json
import random
import sys

import httpx
import pytest

from fuzzer.core import BaselineStrategy, run, save, summarize
from fuzzer.mutators import mutate_request

TARGET = {"url": "http://test/x", "kind": "json"}   # no logs_url -> no server join
SEED = {"username": "alice@example.com", "query": "hello world"}


def mock_client(handler=None):
    handler = handler or (lambda req: httpx.Response(200, json={}, headers={"X-Correlation-ID": "x"}))
    return httpx.Client(transport=httpx.MockTransport(handler))


def once(seed, n=50):
    return run(TARGET, BaselineStrategy(SEED, ["'", "admin"], seed), n, client=mock_client())


# --- determinism + budget (user stories 1 and 3) ---------------------------

def test_budget_is_exact():
    assert len(once(42, 50)) == 50


def test_same_seed_same_payloads():
    assert [r["payload"] for r in once(42)] == [r["payload"] for r in once(42)]


def test_different_seed_differs():
    assert [r["payload"] for r in once(1)] != [r["payload"] for r in once(2)]


# --- mutators ---------------------------------------------------------------

def test_mutations_are_json_serializable_and_seed_untouched():
    rng, before = random.Random(0), dict(SEED)
    for _ in range(500):
        json.dumps(mutate_request(SEED, rng, ["'", "admin"]))
    assert SEED == before


# --- oracle -----------------------------------------------------------------

def test_5xx_is_interesting():
    h = lambda req: httpx.Response(500, text="sqlite3.OperationalError")
    recs = run(TARGET, BaselineStrategy(SEED, [], 1), 3, client=mock_client(h))
    assert all(r["interesting"] for r in recs)


def test_connection_errors_are_recorded_not_raised():
    def h(req):
        raise httpx.ConnectError("boom")
    recs = run(TARGET, BaselineStrategy(SEED, [], 1), 3, client=mock_client(h))
    assert len(recs) == 3 and all(r["status"] is None for r in recs)


def fake_server(depths):
    """Server whose i-th request has depth depths[i]; /logs returns ground truth."""
    state = {"n": 0}

    def handler(req):
        if req.url.path == "/logs":
            entries = [{"correlation_id": f"c{i}", "depth": d, "sink_reached": False}
                       for i, d in enumerate(depths)]
            return httpx.Response(200, json={"entries": entries})
        i = state["n"]
        state["n"] += 1
        return httpx.Response(200, json={}, headers={"X-Correlation-ID": f"c{i}"})
    return mock_client(handler)


def test_new_depth_oracle_ignores_first_request():
    target = {**TARGET, "logs_url": "http://test/logs"}
    recs = run(target, BaselineStrategy(SEED, [], 1), 5, client=fake_server([3, 3, 5, 5, 4]))
    s = summarize(recs)
    assert recs[0]["new_depth"] is False
    assert s["first_interesting"] == 2
    assert s["interesting_total"] == 1
    assert s["max_depth"] == 5


# --- output + safety --------------------------------------------------------

def test_save_writes_valid_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = save(once(42, 5), "t", "baseline", 42, 5)
    data = json.loads(p.read_text())
    assert data["meta"]["seed"] == 42 and len(data["records"]) == 5


def test_refuses_non_local_target(monkeypatch):
    from fuzzer import __main__ as m
    monkeypatch.setitem(m.TARGETS, "evil", {"url": "http://example.com/x", "kind": "json",
                                            "seed_request": {"a": "b"}})
    monkeypatch.setattr(sys, "argv", ["fuzzer", "run", "--target", "evil"])
    with pytest.raises(SystemExit) as e:
        m.main()
    assert "non-local" in str(e.value)