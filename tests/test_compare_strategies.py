import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "compare_strategies", Path(__file__).resolve().parent.parent / "scripts" / "compare_strategies.py")
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def _recs(outcomes):
    return [{"i": i, "outcome": o} for i, o in enumerate(outcomes)]


def test_outcome_auc_rewards_finding_outcomes_earlier():
    early = cs.outcome_auc(_recs(["a", "b", "c", "c", "c", "c"]), 6)     # 1,2,3,3,3,3 -> 15/6
    late = cs.outcome_auc(_recs(["a", "a", "a", "a", "b", "c"]), 6)      # 1,1,1,1,2,3 -> 9/6
    assert early == 15 / 6 and late == 9 / 6 and early > late


def test_outcome_auc_pads_short_runs_and_ignores_missing_outcomes():
    assert cs.outcome_auc(_recs(["a", "b"]), 4) == (1 + 2 + 2 + 2) / 4
    assert cs.outcome_auc([{"i": 0, "outcome": None}, {"i": 1, "outcome": "a"}], 2) == (0 + 1) / 2
    assert cs.outcome_auc([], 10) is None


def test_outcome_auc_orders_by_request_index():
    shuffled = [{"i": 2, "outcome": "c"}, {"i": 0, "outcome": "a"}, {"i": 1, "outcome": "b"}]
    assert cs.outcome_auc(shuffled, 3) == (1 + 2 + 3) / 3


def test_pre_registered_decision_rule():
    assert cs.verdict(0.01, 0.70) == "HELPS"
    assert cs.verdict(0.01, 0.60) == "no evidence"       # significant but effect below A12 >= 0.64
    assert cs.verdict(0.20, 0.90) == "no evidence"       # large effect but not significant
    assert cs.verdict(0.01, 0.30) == "HURTS"
    assert cs.verdict(None, 0.9).startswith("n/a")


def test_n_500_accepts_int_and_json_string_keys():
    assert cs.n_500({"status_counts": {500: 3}}) == 3
    assert cs.n_500({"status_counts": {"500": 2, "400": 9}}) == 2
    assert cs.n_500({}) == 0


def _write_run(d, strategy, seed, outcomes, target="shop", wordlist="mini"):
    import json
    recs = [{"i": i, "outcome": o} for i, o in enumerate(outcomes)]
    summ = dict(distinct_outcomes=len(set(outcomes)), first_interesting=None, sink_hits=0, interesting_total=0,
                status_counts={"400": len(outcomes)})
    meta = dict(target=target, strategy=strategy, seed=seed, budget=len(outcomes), wordlist=wordlist)
    (d / f"run_{target}_{strategy}_{wordlist}_s{seed}.json").write_text(json.dumps({"meta": meta, "summary": summ, "records": recs}))


def test_planted_bugs_are_extracted_per_run(tmp_path):
    _write_run(tmp_path, "baseline", 1, ["order_ok", "sqli_error"])
    _write_run(tmp_path, "ml", 1, ["order_ok", "coupon_parser_crash", "sqli_error", "bad_email"])
    cells, _, rows = cs.load(tmp_path)
    store = cells[("shop", "mini")]
    assert store["baseline"]["bug_sets"] == [["sqli_error"]]
    assert store["ml"]["bug_sets"] == [["coupon_parser_crash", "sqli_error"]]
    assert {r["strategy"]: r["bugs_found"] for r in rows} == {"baseline": "sqli_error", "ml": "coupon_parser_crash;sqli_error"}


def test_bug_table_prints_counts_and_flags_a_tripped_tripwire(tmp_path, capsys):
    _write_run(tmp_path, "baseline", 1, ["order_ok"])
    _write_run(tmp_path, "ml", 1, ["order_ok", "premium_crash"])
    cells, _, _ = cs.load(tmp_path)
    cs.bug_table(cells)
    out = capsys.readouterr().out
    assert "PLANTED BUGS TRIGGERED (shop/mini)" in out and "TRIPWIRE TRIGGERED" in out


def test_bug_table_is_quiet_for_targets_without_planted_bug_labels(tmp_path, capsys):
    _write_run(tmp_path, "baseline", 1, ["a"], target="flask_app")
    _write_run(tmp_path, "ml", 1, ["a"], target="flask_app")
    cells, _, rows = cs.load(tmp_path)
    cs.bug_table(cells)
    assert capsys.readouterr().out == "" and rows[0]["bugs_found"] == ""
