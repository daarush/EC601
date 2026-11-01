import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from fuzzer.core import save

_spec = importlib.util.spec_from_file_location(
    "run_matrix", Path(__file__).resolve().parent.parent / "scripts" / "run_matrix.py")
rm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rm)


def _rec(i):
    return dict(i=i, interesting=False, depth=1, sink_reached=False, outcome="bad_email", status=400)


def test_run_path_matches_where_save_writes(tmp_path):
    written = save([_rec(0)], "shop", "bandit", 66, 1, wordlist="mini", out_dir=tmp_path)
    assert written == rm.run_path(tmp_path, "shop", "bandit", "mini", 66, 1)


def test_is_complete_requires_a_fully_written_run(tmp_path):
    full = save([_rec(i) for i in range(5)], "shop", "ml", 1, 5, wordlist="mini", out_dir=tmp_path)
    assert rm.is_complete(full, 5) is True
    assert rm.is_complete(full, 6) is False                       # run was shorter than the requested budget
    assert rm.is_complete(tmp_path / "missing.json", 5) is False
    broken = tmp_path / "broken.json"
    broken.write_text('{"meta": {}, "records": [{"i": 0}, ')       # crashed mid-write
    assert rm.is_complete(broken, 5) is False
    (tmp_path / "other.json").write_text(json.dumps({"meta": {}}))
    assert rm.is_complete(tmp_path / "other.json", 5) is False


def _patch(monkeypatch, failures):
    calls = {"runs": 0, "strategies": 0, "sleeps": []}

    class Strat:
        name = "baseline"

    def fake_load(name):
        def make(seed_request, words, seed):
            calls["strategies"] += 1
            return Strat()
        return make

    def fake_run(t, strat, budget):
        calls["runs"] += 1
        if calls["runs"] <= failures:
            raise httpx.ConnectError("[WinError 10048] Only one usage of each socket address")
        return ["records"]

    monkeypatch.setattr(rm, "load_strategy", fake_load)
    monkeypatch.setattr(rm, "run", fake_run)
    monkeypatch.setattr(rm.time, "sleep", lambda s: calls["sleeps"].append(s))
    return calls


def test_a_refused_connection_redoes_the_whole_run_with_a_fresh_strategy(monkeypatch):
    calls = _patch(monkeypatch, failures=2)
    strat, records = rm.run_with_retry("baseline", {"seed_request": {}}, [], 1, 10)
    assert records == ["records"] and calls["runs"] == 3
    assert calls["strategies"] == 3                               # a NEW strategy each attempt (no half-trained state)
    assert calls["sleeps"] == [rm.RETRY_WAIT_S, rm.RETRY_WAIT_S]


def test_gives_up_after_max_attempts(monkeypatch):
    calls = _patch(monkeypatch, failures=10 ** 6)
    with pytest.raises(httpx.ConnectError):
        rm.run_with_retry("baseline", {"seed_request": {}}, [], 1, 10)
    assert calls["runs"] == rm.MAX_ATTEMPTS


def test_other_errors_are_not_swallowed(monkeypatch):
    _patch(monkeypatch, failures=0)
    monkeypatch.setattr(rm, "run", lambda *a: (_ for _ in ()).throw(ValueError("real bug")))
    with pytest.raises(ValueError):
        rm.run_with_retry("baseline", {"seed_request": {}}, [], 1, 10)
