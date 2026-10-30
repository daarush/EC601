import random
import re

import pytest

from fuzzer.bandit_strategy import OPS, BanditStrategy, apply_op
from fuzzer.core import BaselineStrategy

SEED_REQ = {"username": "alice@example.com", "query": "hello world"}
WORDS = ["'", "admin", "SEARCH:", "--"]


def _rec(payload, status=400, body='{"error":"bad"}', **extra):
    rec = dict(status=status, body=body, payload=payload, client_interesting=False)
    rec.update(extra)
    return rec


# ------------------------------------------------------------------ operators
@pytest.mark.parametrize("op", [o for o in OPS if o not in ("drop", "type")])
def test_every_string_operator_returns_a_string(op):
    rng = random.Random(1)
    for value in ("hello world", "", "a", "x" * 300, 42, None):
        assert isinstance(apply_op(value, op, rng, WORDS), str)


def test_dict_operators_use_the_wordlist_and_tolerate_an_empty_one():
    rng = random.Random(1)
    assert apply_op("hello", "dict_replace", rng, ["SEARCH:"]) == "SEARCH:"
    assert "SEARCH:" in apply_op("hello", "dict_insert", rng, ["SEARCH:"])
    assert apply_op("hello", "dict_replace", rng, []) == "hello"


def test_operators_are_deterministic_per_rng():
    assert apply_op("hello world", "flip", random.Random(5), WORDS) == apply_op("hello world", "flip", random.Random(5), WORDS)


# ------------------------------------------------------------------ interface
def test_arms_are_fields_times_operators():
    s = BanditStrategy(SEED_REQ, WORDS, 1)
    assert len(s.arms) == len(SEED_REQ) * len(OPS)
    assert ("query", "dict_replace") in s.arms and ("username", "drop") in s.arms


def test_first_payload_is_seed_then_dicts_only():
    s = BanditStrategy(SEED_REQ, WORDS, 1)
    first = s.next_payload()
    assert first == SEED_REQ and first is not SEED_REQ
    for _ in range(50):
        p = s.next_payload()
        assert isinstance(p, dict)
        s.observe(_rec(p))


def test_deterministic_with_same_seed():
    def trace(seed):
        s, out = BanditStrategy(SEED_REQ, WORDS, seed), []
        for i in range(80):
            p = s.next_payload()
            out.append(p)
            s.observe(_rec(p, status=400 + i % 3, body=f'{{"error":"m{i % 3}"}}'))
        return out
    assert trace(3) == trace(3) and trace(3) != trace(4)


def test_ignores_server_side_ground_truth():
    def trace(extra):
        s, out = BanditStrategy(SEED_REQ, WORDS, 5), []
        for i in range(60):
            p = s.next_payload()
            out.append(p)
            s.observe(_rec(p, status=400 + i % 3, body=f'{{"error":"m{i % 3}"}}', **extra(i)))
        return out
    clean = trace(lambda i: {})
    leaky = trace(lambda i: dict(depth=i % 7, new_depth=True, sink_reached=True, outcome=f"o{i}", interesting=True))
    assert clean == leaky


# ------------------------------------------------------------------ learning
def test_rare_response_raises_the_posterior_of_the_arms_that_caused_it():
    s = BanditStrategy(SEED_REQ, WORDS, 1)
    s._last_arms = []
    for _ in range(30):                                                       # establish a common response kind
        s.observe(_rec({}, status=400, body='{"error":"common"}'))
    winner, loser = ("query", "dict_replace"), ("username", "flip")
    a0, b0 = s.alpha[winner], s.beta[winner]
    s._last_arms = [winner]
    s.observe(_rec({}, status=200, body='{"result":"NEVER SEEN BEFORE"}'))   # new kind => success
    assert s.alpha[winner] == pytest.approx(a0 + 1.0) and s.beta[winner] == pytest.approx(b0)
    s._last_arms = [loser]
    a1, b1 = s.alpha[loser], s.beta[loser]
    for _ in range(20):                                                       # common kind => failure
        s.observe(_rec({}, status=400, body='{"error":"common"}'))
    assert s.alpha[loser] == pytest.approx(a1) and s.beta[loser] == pytest.approx(b1 + 20)


def test_is_rare_rule():
    from fuzzer.bandit_strategy import is_rare
    assert is_rare(1, 10, 3)                  # brand new kind
    assert is_rare(2, 100, 3)                 # rarer than the average kind (2% < 33%)
    assert not is_rare(90, 100, 3)            # dominant kind
    assert not is_rare(5, 5, 1)               # only one kind seen so far => nothing is rare


def _oracle(payload):
    """Toy target: the RARE response happens only if `query` starts with an OPERATION: token."""
    q = payload.get("query")
    if isinstance(q, str) and re.match(r"^[A-Za-z_]+:", q):
        return 200, '{"result":"reached the interesting code"}'
    return 400, '{"error":"rejected"}'


def _run(strategy, n=300):
    hits = 0
    for _ in range(n):
        p = strategy.next_payload()
        status, body = _oracle(p)
        hits += status == 200
        strategy.observe(_rec(p, status=status, body=body))
    return hits


def test_bandit_finds_the_rare_response_more_often_than_the_baseline():
    bandit_total = base_total = 0
    for seed in (1, 2, 3, 4, 5):
        bandit_total += _run(BanditStrategy(SEED_REQ, WORDS, seed))
        base_total += _run(BaselineStrategy(SEED_REQ, WORDS, seed))
    assert bandit_total >= 1.5 * max(base_total, 1), (bandit_total, base_total)


def test_bandit_learns_which_field_and_operator_matter():
    s = BanditStrategy(SEED_REQ, WORDS, 2)
    _run(s, n=400)
    top = s.arm_summary(4)
    assert any(r["field"] == "query" and r["operator"] in ("dict_replace", "dict_insert") for r in top), top


# ------------------------------------------------------------------ metadata
def test_params_and_arm_summary_are_exposed_and_serialisable():
    import json
    s = BanditStrategy(SEED_REQ, WORDS, 1)
    s.next_payload()
    for _ in range(20):
        s.observe(_rec(s.next_payload()))
    p = s.params
    json.dumps(p)
    assert p["n_arms"] == len(s.arms) and len(p["arm_summary"]) == 10
    assert {"field", "operator", "pulls", "posterior_mean"} <= set(p["arm_summary"][0])
