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
