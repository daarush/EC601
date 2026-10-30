"""LLM-assisted strategy: schema-constrained payload generation with a black-box feedback loop.

What it does
------------
Every ``batch_size`` requests the strategy asks an LLM for a batch of new payloads. The model sees
only what a human black-box tester would see:

* the field names and one known-good example request (with the response it produced),
* a table of the *kinds* of responses seen so far (status + start of the body), how often each
  occurred, and an example payload for each -- this is where validation rejection messages
  ("must be user@domain.tld", ...) reach the model,
* the results of the most recent batch.

It never sees server-side ground truth (depth, outcome, sink flags), the target URL, the source code,
or the wordlist. The wordlist is the baseline's/ML's prior knowledge; the LLM's prior is its training.

Output is forced through a tool call with a JSON schema, so payloads are structurally valid and
measurable. Anything invalid is dropped and counted.

Fairness / honesty notes
------------------------
* Same request budget as the other variants: the LLM proposes, each proposal costs one request.
* Cost is reported, not hidden: calls, input/output tokens and latency are saved in ``meta.params.usage``.
* LLM sampling is NOT controlled by ``seed``; runs are not bit-reproducible. ``seed`` only drives the
  fallback mutator. To keep runs auditable the per-call transcript (counts, intents, tokens,
  latency) and the first prompt are saved in ``meta.params``.
* If the API fails after retries, the batch is filled with baseline mutations so the budget is still
  spent; ``usage.fallback_payloads`` counts them. Treat runs with many fallbacks as invalid.
"""
from __future__ import annotations

import json
import os
import random
import time

import httpx

from .ml_strategy import signature
from .mutators import mutate_request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-5-5"      # override with FUZZ_LLM_MODEL
TOOL_NAME = "submit_payloads"

BATCH_SIZE = 25
MAX_GROUPS_IN_PROMPT = 12
LAST_RESULTS_IN_PROMPT = 15
VALUE_CLIP = 80                 # chars of each payload value shown back to the model
BODY_CLIP = 140                 # chars of each response body shown back to the model
MAX_VALUE_LEN = 300             # longer generated values are clipped (keeps requests sane)

SYSTEM_PROMPT = (
    "You assist an AUTHORIZED, black-box security test of a local test web application that the tester "
    "owns. You cannot see its source code. Your job is to propose HTTP request payloads that (1) get "
    "past the application's input validation so they reach deeper logic, and (2) are likely to expose "
    "vulnerabilities such as injection or unhandled errors. Learn from the responses: rejection "
    "messages usually say what the application expects. Always answer by calling the submit_payloads tool."
)


def build_schema(field_names: list[str], batch_size: int) -> dict:
    fields = {k: {"type": "string"} for k in field_names}
    return {
        "type": "object",
        "properties": {
            "payloads": {
                "type": "array",
                "maxItems": batch_size,
                "items": {
                    "type": "object",
                    "properties": {
                        "fields": {"type": "object", "properties": fields,
                                   "required": list(field_names), "additionalProperties": False},
                        "intent": {"type": "string", "description": "<= 12 words: what this probes"},
                    },
                    "required": ["fields", "intent"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["payloads"],
        "additionalProperties": False,
    }


def _clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n] + "..."


class AnthropicClient:
    """Minimal Messages-API client (httpx only, no extra dependency). Forces one tool call."""

    def __init__(self, model=None, api_key=None, timeout=90.0, max_tokens=4096, retries=3):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (needed for the 'llm' strategy).")
        self.model = model or os.environ.get("FUZZ_LLM_MODEL", DEFAULT_MODEL)
        self.max_tokens, self.retries = max_tokens, retries
        self.temperature = os.environ.get("FUZZ_LLM_TEMPERATURE")      # optional; omitted by default
        self.http = httpx.Client(timeout=timeout)

    def __call__(self, system: str, user: str, schema: dict) -> tuple[list[dict], dict]:
        body = {
            "model": self.model, "max_tokens": self.max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"name": TOOL_NAME, "description": "Submit the next batch of request payloads.",
                       "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": TOOL_NAME},
        }
        if self.temperature is not None:
            body["temperature"] = float(self.temperature)
        headers = {"x-api-key": self.api_key, "anthropic-version": API_VERSION,
                   "content-type": "application/json"}
        last_err = None
        for attempt in range(self.retries):
            try:
                r = self.http.post(API_URL, headers=headers, json=body)
                if r.status_code in (429, 500, 502, 503, 529):
                    raise httpx.HTTPError(f"retryable status {r.status_code}")
                r.raise_for_status()
                data = r.json()
                items = []
                for block in data.get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME:
                        items = block.get("input", {}).get("payloads", [])
                usage = data.get("usage", {})
                return items, {"input_tokens": usage.get("input_tokens", 0),
                               "output_tokens": usage.get("output_tokens", 0)}
            except (httpx.HTTPError, ValueError) as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after {self.retries} attempts: {last_err!r}")


class LLMStrategy:
    name = "llm"

    def __init__(self, seed_request, words, seed, *, llm=None, batch_size=BATCH_SIZE):
        self.seed_request, self.words, self.seed = seed_request, words, seed
        self.batch_size = batch_size
        self.llm = llm or AnthropicClient()
        self.model = getattr(self.llm, "model", "injected")
        self.rng = random.Random(seed)             # drives ONLY the fallback mutator
        self.first = True
        self._queue: list[dict] = []
        self._intents: dict[str, str] = {}
        self._sent: set[str] = set()
        self._history: list[dict] = []             # client-visible (payload, status, body)
        self._groups: dict[tuple, dict] = {}       # signature -> {count, example_payload, example_body, status}
        self._schema = build_schema(sorted(seed_request), batch_size)
        self.usage = dict(calls=0, input_tokens=0, output_tokens=0, latency_ms=0.0, proposed_payloads=0,
                          valid_payloads=0, invalid_payloads=0, duplicate_payloads=0,
                          fallback_payloads=0, failed_calls=0)
        self.transcript: list[dict] = []
        self.example_prompt: str | None = None

    # ---- reproducibility metadata ----------------------------------------------------------
    @property
    def params(self) -> dict:
        return dict(model=self.model, batch_size=self.batch_size, sees_wordlist=False,
                    sees_server_ground_truth=False, usage=self.usage, transcript=self.transcript,
                    example_prompt=self.example_prompt, system_prompt=SYSTEM_PROMPT)

    # ---- strategy interface ----------------------------------------------------------------
    def next_payload(self) -> dict:
        if self.first:
            self.first = False
            p = dict(self.seed_request)             # calibration request, same as the other variants
            self._sent.add(json.dumps(p, sort_keys=True))
            return p
        if not self._queue:
            self._refill()
        return self._queue.pop(0)

    def observe(self, rec: dict) -> None:
        payload = rec.get("payload", {})
        status, body = rec.get("status"), rec.get("body", "")
        self._history.append(dict(payload=payload, status=status, body=body))
        sig = signature(rec)
        g = self._groups.setdefault(sig, dict(count=0, status=status, example_payload=payload,
                                              example_body=body))
        g["count"] += 1

    # ---- generation ------------------------------------------------------------------------
    def _refill(self) -> None:
        prompt = self._build_prompt()
        if self.example_prompt is None:
            self.example_prompt = prompt
        t0 = time.perf_counter()
        call = dict(idx=self.usage["calls"], prompt_chars=len(prompt))
        try:
            items, tok = self.llm(SYSTEM_PROMPT, prompt, self._schema)
            latency = (time.perf_counter() - t0) * 1000
            self.usage["calls"] += 1
            self.usage["input_tokens"] += tok.get("input_tokens", 0)
            self.usage["output_tokens"] += tok.get("output_tokens", 0)
            self.usage["latency_ms"] += latency
            call.update(latency_ms=round(latency, 1), **tok)
        except Exception as e:                       # API down / rate limited / bad key
            self.usage["failed_calls"] += 1
            call.update(error=repr(e)[:200])
            items = []
        if isinstance(items, list):
            items = items[:self.batch_size]          # schema maxItems is advisory; enforce it ourselves
        valid = self._accept(items)
        call.update(proposed=len(items), accepted=len(valid), intents=[self._intents.get(json.dumps(p, sort_keys=True), "")
                                                                         for p in valid][:self.batch_size])
        self.transcript.append(call)
        self._queue.extend(valid[:self.batch_size])
        while len(self._queue) < self.batch_size:    # top up with baseline mutations so budget is always spent
            p = mutate_request(self.seed_request, self.rng, self.words)
            self._queue.append(p)
            self.usage["fallback_payloads"] += 1

    def _accept(self, items) -> list[dict]:
        out = []
        keys = set(self.seed_request)
        for it in items if isinstance(items, list) else []:
            self.usage["proposed_payloads"] += 1
            fields = it.get("fields") if isinstance(it, dict) else None
            if not isinstance(fields, dict) or set(fields) != keys:
                self.usage["invalid_payloads"] += 1
                continue
            payload = {k: str(v)[:MAX_VALUE_LEN] for k, v in fields.items()}
            key = json.dumps(payload, sort_keys=True)
            if key in self._sent:
                self.usage["duplicate_payloads"] += 1
                continue
            self._sent.add(key)
            self._intents[key] = str(it.get("intent", ""))[:120]
            self.usage["valid_payloads"] += 1
            out.append(payload)
        return out

    def _build_prompt(self) -> str:
        n = len(self._history)
        lines = []
        lines.append("ENDPOINT CONTEXT")
        lines.append(f"Request fields: {sorted(self.seed_request)}")
        lines.append(f"Known-good example request: {json.dumps(self.seed_request)}")
        if self._history:
            first = self._history[0]
            lines.append(f"Response to the example (status {first['status']}): {_clip(first['body'], BODY_CLIP)}")
        lines.append("")
        lines.append(f"REQUESTS SENT SO FAR: {n}")
        if self._groups:
            lines.append("KINDS OF RESPONSE SEEN (rarest first): count | status | response excerpt | example payload")
            ordered = sorted(self._groups.values(), key=lambda g: g["count"])[:MAX_GROUPS_IN_PROMPT]
            for g in ordered:
                ex = {k: _clip(v, VALUE_CLIP) for k, v in g["example_payload"].items()}
                lines.append(f"- {g['count']} | {g['status']} | {_clip(g['example_body'], BODY_CLIP)} | {json.dumps(ex)}")
        recent = self._history[-LAST_RESULTS_IN_PROMPT:]
        if len(recent) > 1:
            lines.append("")
            lines.append("MOST RECENT RESULTS: payload -> status, response excerpt")
            for h in recent:
                ex = {k: _clip(v, VALUE_CLIP) for k, v in h["payload"].items()}
                lines.append(f"- {json.dumps(ex)} -> {h['status']}, {_clip(h['body'], 100)}")
        lines.append("")
        lines.append(
            f"Propose {self.batch_size} NEW payloads (each must contain every field: {sorted(self.seed_request)}). "
            "Read the rejection messages above and fix whatever they complain about so payloads get further; "
            "once a payload gets past validation, vary it to probe for vulnerabilities (injection, "
            "special characters, boundary values, unexpected formats). Do not repeat earlier payloads. "
            "Keep values under 200 characters. Give each a short intent.")
        return "\n".join(lines)
