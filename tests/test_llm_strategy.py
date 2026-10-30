import json

import httpx
import pytest

from fuzzer import llm_strategy
from fuzzer.core import run
from fuzzer.llm_strategy import SYSTEM_PROMPT, TOOL_NAME, AnthropicClient, LLMStrategy, build_schema

SEED_REQ = {"username": "alice@example.com", "query": "hello world"}
WORDS = ["SECRETWORDLISTENTRY", "admin"]


def item(username, query, intent="probe"):
    return {"fields": {"username": username, "query": query}, "intent": intent}


class FakeLLM:
    """Stands in for the API: returns scripted batches and records every prompt it was shown."""
    model = "fake-model"

    def __init__(self, batches=None, tokens=(100, 50)):
        self.batches, self.tokens, self.prompts, self.calls = list(batches or []), tokens, [], 0

    def __call__(self, system, user, schema):
        self.calls += 1
        self.prompts.append(user)
        items = self.batches.pop(0) if self.batches else [item(f"u{self.calls}_{i}@x.com", f"q{self.calls}_{i}") for i in range(50)]
        return items, {"input_tokens": self.tokens[0], "output_tokens": self.tokens[1]}


def _rec(payload, status=400, body='{"error":"bad"}', **extra):
    r = dict(status=status, body=body, payload=payload, client_interesting=False)
    r.update(extra)
    return r


# ------------------------------------------------------------------ schema
def test_schema_forces_structure():
    s = build_schema(["username", "query"], 25)
    items = s["properties"]["payloads"]
    assert items["maxItems"] == 25 and s["additionalProperties"] is False
    fields = items["items"]["properties"]["fields"]
    assert set(fields["required"]) == {"username", "query"} and fields["additionalProperties"] is False


# ------------------------------------------------------------------ strategy behaviour
def test_first_payload_is_seed_then_llm_batch():
    llm = FakeLLM([[item("a@b.com", "SEARCH:x"), item("c@d.com", "SEARCH:y")]])
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=llm, batch_size=2)
    assert s.next_payload() == SEED_REQ
    assert llm.calls == 0                               # calibration request costs no LLM call
    assert s.next_payload() == {"username": "a@b.com", "query": "SEARCH:x"}
    assert llm.calls == 1
    assert s.next_payload() == {"username": "c@d.com", "query": "SEARCH:y"}
    assert llm.calls == 1                               # batch is consumed before another call


def test_invalid_items_are_dropped_and_counted():
    bad = [{"fields": {"username": "only"}, "intent": "x"},            # missing field
           {"fields": {"username": "a", "query": "b", "extra": "c"}, "intent": "x"},   # extra field
           "not a dict", {"intent": "no fields"}, item("ok@x.com", "fine")]
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=FakeLLM([bad]), batch_size=5)
    s.next_payload()
    assert s.next_payload() == {"username": "ok@x.com", "query": "fine"}
    assert s.usage["invalid_payloads"] == 4 and s.usage["valid_payloads"] == 1


def test_duplicates_including_the_seed_are_dropped():
    dup = [item("alice@example.com", "hello world"), item("n@x.com", "one"), item("n@x.com", "one")]
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=FakeLLM([dup]), batch_size=3)
    s.next_payload()
    s.next_payload()
    assert s.usage["duplicate_payloads"] == 2 and s.usage["valid_payloads"] == 1


def test_values_are_strings_and_clipped():
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=FakeLLM([[item("a" * 5000, 123)]]), batch_size=1)
    s.next_payload()
    p = s.next_payload()
    assert all(isinstance(v, str) for v in p.values()) and len(p["username"]) == llm_strategy.MAX_VALUE_LEN


def test_api_failure_falls_back_to_baseline_mutations_and_spends_budget():
    def boom(system, user, schema):
        raise RuntimeError("rate limited")
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=boom, batch_size=5)
    s.next_payload()
    payloads = [s.next_payload() for _ in range(5)]
    assert len(payloads) == 5 and all(isinstance(p, dict) for p in payloads)
    assert s.usage["failed_calls"] == 1 and s.usage["fallback_payloads"] == 5
    assert "error" in s.transcript[0]


def test_short_batches_are_topped_up():
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=FakeLLM([[item("a@b.com", "x")]]), batch_size=4)
    s.next_payload()
    got = [s.next_payload() for _ in range(4)]
    assert got[0] == {"username": "a@b.com", "query": "x"}
    assert s.usage["fallback_payloads"] == 3


def test_token_and_latency_usage_accumulates():
    llm = FakeLLM(tokens=(1000, 200))
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=llm, batch_size=3)
    s.next_payload()
    for i in range(7):                                   # 7 payloads => 3 LLM calls
        s.observe(_rec(s.next_payload()))
    assert s.usage["calls"] == 3
    assert s.usage["input_tokens"] == 3000 and s.usage["output_tokens"] == 600 and s.usage["latency_ms"] >= 0


# ------------------------------------------------------------------ what the model is (and is not) shown
def test_prompt_contains_client_visible_feedback_only():
    llm = FakeLLM()
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=llm, batch_size=3)
    s.observe(_rec(s.next_payload(), status=400, body='{"error":"Query must look like <OPERATION>:<argument>"}',
                   depth=9, outcome="SECRET_OUTCOME", sink_reached=True, new_depth=True))
    s.next_payload()
    prompt = llm.prompts[0]
    assert "Query must look like" in prompt                      # rejection reason reaches the model
    assert "username" in prompt and "alice@example.com" in prompt
    for forbidden in ("SECRET_OUTCOME", "sink_reached", "new_depth", "depth", "SECRETWORDLISTENTRY"):
        assert forbidden not in prompt, forbidden


def test_prompt_lists_rarest_response_kinds_first():
    llm = FakeLLM()
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=llm, batch_size=2)
    s.next_payload()
    for i in range(6):
        s.observe(_rec({"username": f"x{i}", "query": "q"}, body='{"error":"COMMON rejection"}'))
    s.observe(_rec({"username": "y", "query": "z"}, status=200, body='{"result":"RAREKIND"}'))
    s.next_payload()
    table = llm.prompts[0].split("KINDS OF RESPONSE")[1].split("MOST RECENT RESULTS")[0]
    assert table.index("RAREKIND") < table.index("COMMON rejection")


def test_params_are_json_serialisable_and_declare_blindness():
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=FakeLLM(), batch_size=2)
    s.next_payload(); s.next_payload()
    p = s.params
    json.dumps(p)
    assert p["sees_wordlist"] is False and p["sees_server_ground_truth"] is False
    assert p["system_prompt"] == SYSTEM_PROMPT and p["example_prompt"] and p["transcript"][0]["accepted"] == 2


def test_end_to_end_with_core_run_spends_exactly_the_budget():
    def handler(request):
        return httpx.Response(400, json={"error": "nope"}, headers={"X-Correlation-ID": "c"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    target = dict(url="http://127.0.0.1:1/x", kind="json", seed_request=SEED_REQ)
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=FakeLLM(), batch_size=10)
    records = run(target, s, 37, client=client)
    assert len(records) == 37 and records[0]["payload"] == SEED_REQ
    assert s.usage["calls"] == 4                         # ceil(36 / 10)


# ------------------------------------------------------------------ API client (no network)
def _client_with(handler, monkeypatch):
    monkeypatch.setattr(llm_strategy.time, "sleep", lambda s: None)
    c = AnthropicClient(api_key="test-key", model="m")
    c.http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient()


def test_client_forces_tool_call_and_parses_result(monkeypatch):
    seen = {}

    def handler(request):
        seen["headers"], seen["body"] = request.headers, json.loads(request.content)
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "ignored"},
                        {"type": "tool_use", "name": TOOL_NAME, "id": "t", "input": {"payloads": [item("a@b.com", "x")]}}],
            "usage": {"input_tokens": 11, "output_tokens": 7}})
    c = _client_with(handler, monkeypatch)
    items, tok = c("sys", "user", build_schema(["username", "query"], 5))
    assert items == [item("a@b.com", "x")] and tok == {"input_tokens": 11, "output_tokens": 7}
    assert seen["headers"]["x-api-key"] == "test-key" and "anthropic-version" in seen["headers"]
    assert seen["body"]["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert seen["body"]["tools"][0]["input_schema"]["required"] == ["payloads"]
    assert "temperature" not in seen["body"]            # omitted unless explicitly configured


def test_client_retries_then_succeeds(monkeypatch):
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(200, json={"content": [], "usage": {}})
    c = _client_with(handler, monkeypatch)
    assert c("s", "u", {})[0] == [] and len(attempts) == 3


def test_client_gives_up_after_retries(monkeypatch):
    c = _client_with(lambda r: httpx.Response(500, json={}), monkeypatch)
    with pytest.raises(RuntimeError, match="failed after"):
        c("s", "u", {})


def test_overlong_batches_are_truncated_before_validation():
    llm = FakeLLM([[item(f"u{i}@x.com", f"q{i}") for i in range(10)]])
    s = LLMStrategy(SEED_REQ, WORDS, 1, llm=llm, batch_size=3)
    s.next_payload(); s.next_payload()
    assert s.usage["proposed_payloads"] == 3 and s.usage["valid_payloads"] == 3
