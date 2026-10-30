import re

import pytest

from fuzzer.core import BaselineStrategy
from fuzzer.features import extract_features, feature_names
from fuzzer.ml_strategy import MLStrategy, rarity_reward, signature

SEED_REQ = {"username": "alice@example.com", "query": "hello world"}
WORDS = ["'", "admin", "SEARCH:", "--"]


def _rec(payload, status=400, body='{"error":"bad"}', **extra):
    rec = dict(status=status, body=body, body_len=len(body), payload=payload,
               client_interesting=False, latency_ms=1.0)
    rec.update(extra)
    return rec


# ---------------------------------------------------------------- features
def test_feature_vector_matches_names():
    names = feature_names(SEED_REQ)
    assert len(extract_features(dict(SEED_REQ), SEED_REQ)) == len(names)
    assert len(set(names)) == len(names)


def test_features_are_deterministic_and_numeric():
    p = {"username": "x'--", "query": "SEARCH:abc"}
    a, b = extract_features(p, SEED_REQ), extract_features(p, SEED_REQ)
    assert a == b and all(isinstance(v, float) for v in a)


def test_features_are_per_field():
    names = feature_names(SEED_REQ)
    quote_in_user = dict(zip(names, extract_features({"username": "a'", "query": "hello world"}, SEED_REQ)))
    quote_in_query = dict(zip(names, extract_features({"username": "alice@example.com", "query": "a'"}, SEED_REQ)))
    assert quote_in_user["username.has_quote"] == 1.0 and quote_in_user["query.has_quote"] == 0.0
    assert quote_in_query["query.has_quote"] == 1.0 and quote_in_query["username.has_quote"] == 0.0


def test_validity_shaped_features():
    names = feature_names(SEED_REQ)
    f = dict(zip(names, extract_features({"username": "alice@example.com", "query": "SEARCH:x"}, SEED_REQ)))
    assert f["username.email_like"] == 1.0 and f["query.op_prefix"] == 1.0
    g = dict(zip(names, extract_features({"username": "alice", "query": "hello"}, SEED_REQ)))
    assert g["username.email_like"] == 0.0 and g["query.op_prefix"] == 0.0


@pytest.mark.parametrize("payload", [
    {}, {"username": None, "query": 0}, {"username": [], "query": {}}, {"username": True, "query": 3.14},
    {"username": "\x00", "query": "😀" * 50}, {"username": "A" * 5000},
])
def test_features_survive_weird_payloads(payload):
    assert len(extract_features(payload, SEED_REQ)) == len(feature_names(SEED_REQ))


def test_no_response_derived_features():
    assert not any("len_dev" in n or "wordlist" in n for n in feature_names(SEED_REQ))


# ---------------------------------------------------------------- reward / signature
def test_rarity_reward_decreases_with_count():
    assert rarity_reward(1) == 1.0 and rarity_reward(4) == 0.25
    assert rarity_reward(1) > rarity_reward(2) > rarity_reward(100)


def test_signature_normalises_digits_and_uuids():
    a = signature({"status": 400, "body": '{"error":"retry 12 id 123e4567-e89b-12d3-a456-426614174000"}'})
    b = signature({"status": 400, "body": '{"error":"retry 99 id 00000000-0000-0000-0000-000000000000"}'})
    assert a == b
    assert signature({"status": 400, "body": "x"}) != signature({"status": 500, "body": "x"})


# ---------------------------------------------------------------- fairness / interface
def test_next_payload_returns_dict_and_first_is_seed():
    s = MLStrategy(SEED_REQ, WORDS, 1)
    first = s.next_payload()
    assert first == SEED_REQ and first is not SEED_REQ
    assert isinstance(s.next_payload(), dict)


def test_identical_to_baseline_until_first_fit():
    """Same seed => same payloads as the baseline for the whole warmup. Fair comparison."""
    ml = MLStrategy(SEED_REQ, WORDS, 7, warmup=15, retrain_every=15)
    base = BaselineStrategy(SEED_REQ, WORDS, 7)
    for _ in range(15):
        p_ml, p_base = ml.next_payload(), base.next_payload()
        assert p_ml == p_base
        ml.observe(_rec(p_ml))
        base.observe(_rec(p_base))
    assert ml.model is not None


def test_not_fitted_before_warmup():
    s = MLStrategy(SEED_REQ, WORDS, 1, warmup=10, retrain_every=10)
    for _ in range(9):
        p = s.next_payload()
        s.observe(_rec(p))
    assert s.model is None


def test_deterministic_with_same_seed():
    def trace(seed):
        s, out = MLStrategy(SEED_REQ, WORDS, seed, warmup=10, retrain_every=10), []
        for i in range(60):
            p = s.next_payload()
            out.append(p)
            s.observe(_rec(p, status=400 + (i % 3), body=f'{{"error":"m{i % 3}"}}'))
        return out
    assert trace(3) == trace(3)
    assert trace(3) != trace(4)


def test_ignores_server_side_ground_truth():
    """Server fields must not influence the strategy, even if they were present."""
    def trace(extra):
        s, out = MLStrategy(SEED_REQ, WORDS, 5, warmup=10, retrain_every=10), []
        for i in range(60):
            p = s.next_payload()
            out.append(p)
            s.observe(_rec(p, status=400 + (i % 3), body=f'{{"error":"m{i % 3}"}}', **extra(i)))
        return out
    clean = trace(lambda i: {})
    leaky = trace(lambda i: dict(depth=i % 7, new_depth=bool(i % 2), sink_reached=bool(i % 5 == 0),
                                 outcome=f"o{i}", interesting=True))
    assert clean == leaky


def test_constant_responses_do_not_crash_and_still_explore():
    s = MLStrategy(SEED_REQ, WORDS, 2, warmup=10, retrain_every=10)
    seen = set()
    for _ in range(80):
        p = s.next_payload()
        seen.add(repr(p))
        s.observe(_rec(p))                  # every response identical -> constant labels
    assert len(seen) > 40                   # ties are broken randomly, not "always candidate #1"


# ---------------------------------------------------------------- the model really learns
def _oracle(payload):
    """Toy target: the RARE response happens only if `query` starts with an OPERATION: token."""
    q = payload.get("query")
    if isinstance(q, str) and re.match(r"^[A-Za-z_]+:", q):
        return 200, '{"result":"reached the interesting code"}'
    return 400, '{"error":"rejected"}'


def _hits(strategy, n=300):
    hits = 0
    for _ in range(n):
        p = strategy.next_payload()
        status, body = _oracle(p)
        hits += status == 200
        strategy.observe(_rec(p, status=status, body=body))
    return hits


def test_ml_finds_rare_response_more_often_than_baseline_logic():
    ml_total = base_total = 0
    for seed in (1, 2, 3, 4, 5):
        ml_total += _hits(MLStrategy(SEED_REQ, WORDS, seed, warmup=30, retrain_every=20))
        base_total += _hits(BaselineStrategy(SEED_REQ, WORDS, seed))
    assert ml_total >= 2 * max(base_total, 1), (ml_total, base_total)


# ---------------------------------------------------------------- reproducibility / explainability
def test_params_are_exposed_for_run_metadata():
    p = MLStrategy(SEED_REQ, WORDS, 1).params
    for key in ("warmup", "n_candidates", "retrain_every", "epsilon", "model", "reward"):
        assert key in p


def test_model_summary_reports_features_after_fit():
    s = MLStrategy(SEED_REQ, WORDS, 1, warmup=10, retrain_every=10)
    for i in range(30):
        p = s.next_payload()
        s.observe(_rec(p, status=400 + (i % 2), body=f'{{"error":"m{i % 2}"}}'))
    summ = s.model_summary()
    assert summ["fitted"] and summ["n_samples"] == 30 and len(summ["top_features"]) == 5
