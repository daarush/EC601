# Sprint 1 Recap: Baseline Black-Box Web Fuzzer + Two Instrumented Targets

**Student:** Aarush Duvvuri (solo) · **Course:** EC 601 · **Date:** 2026-10-09

---

## 1. Results (headline)

All runs: baseline mutation strategy, budget 200 requests, seed 42, dictionary `data/wordlists/mini.txt` (uninformed: contains no target-specific tokens). Request 0 is an unmutated calibration request.

| Metric | Site A (`flask_app`, JSON, multi-stage validation) | Site B (`vuln_site`, GET, real SQLite injection) |
|---|---|---|
| Requests sent | 200 | 200 |
| `first_interesting` (request index) | **None** | 65 |
| `interesting_total` | **0** | 2 |
| `max_depth` reached | 6 (same as the unmutated seed) | 4 (same as the unmutated seed) |
| `sink_hits` | **0** | 100 (SQL executed) |
| Status counts | 400: 199, 403: 1 | 200: 98, 400: 100, 500: 2 |

**Tests:** 30 passed in 0.31 s (`uv run pytest -q`), no servers required.

**How to read these numbers**

- **Site A:** An uninformed mutation baseline made no progress in 200 requests. It never got past the depth of its own starting request and never reached the sink. This is weak but real evidence for the riskiest assumption in SPRINT1 §7 (that the baseline does not saturate the target).
- **Site B:** The baseline reaches the SQL layer easily (max depth 4 is reached immediately). The informative number is the 500 count: 2 of 200 requests triggered a real `sqlite3.OperationalError`, the first at request 65. Site B is a sanity target showing the fuzzer finds natural bugs, not a hard benchmark.
- **`sink_hits` on Site B** means "SQL was executed", including the 500s. It does not mean "exploited".
- **Caveat:** each cell is a single run (n = 1, one seed). Nothing here is statistically meaningful yet. The 30-run protocol with Mann-Whitney U and A12 in SPRINT1 §8 is a later sprint.

---

## 2. Conclusion

Sprint 1 produced a working experimental foundation:

1. **Two instrumented targets** with different shapes (JSON body with a deep validation chain vs. GET params with a real injection), each logging ground truth keyed by correlation ID.
2. **A deterministic baseline fuzzer** with an exact request budget, seed control, and a `Strategy` interface (`next_payload`, `observe`) that the ML and LLM variants will plug into later.
3. **An oracle implementing SPRINT1 §8:** 5xx, error signature, or new depth reached (server-confirmed).
4. **30 automated tests** covering target behavior, determinism, budget, oracle logic, and the local-only safety allowlist.

**What the results support:** an uninformed dictionary and mutation baseline does not trivially saturate Site A.

**What they do not support yet:**

- Whether a *better-informed* baseline would saturate Site A. This is the real test of the riskiest assumption, and it has not been run (see §6).
- Any claim about ML or LLM variants. None exist yet.
- Any statistical claim. These are single runs.

---

## 3. System overview

```
             ┌─────────────────────────── fuzzer/ ───────────────────────────┐
 CLI ───────▶│ __main__.py  parse args, allowlist check, load wordlist         │
             │      │                                                          │
             │      ▼                                                          │
             │ core.run(): for i in range(budget):                             │
             │      payload = strategy.next_payload()   ◀── mutators.py        │
             │      send (JSON body or query string)    ──────────────┐        │
             │      record status/body/latency/X-Correlation-ID       │        │
             │      strategy.observe(record)                          │        │
             │      │                                                 │        │
             │      ▼ after the loop                                  ▼        │
             │ _join_server_log(): GET /logs ──▶ match by correlation ID       │
             │      attach depth, sink_reached; compute new_depth, interesting │
             │      │                                                          │
             │      ▼                                                          │
             │ summarize() + save()  ──▶ results/run_<target>_..._b<N>.json   │
             └────────────────────────────────────────────────────────────────┘
                                                      │
                          HTTP                        ▼
             ┌──────────────────────────┐   ┌──────────────────────────┐
             │ Site A  :5000  /submit   │   │ Site B  :5001  /search   │
             │ /logs  /reset            │   │ /logs  /reset            │
             └──────────────────────────┘   └──────────────────────────┘
```

The key design point is that the fuzzer is **black-box on the wire**: it only sees HTTP status, body, and the `X-Correlation-ID` header while fuzzing. The server-side log is read **after** the run, solely to compute ground-truth metrics. The baseline never sees it, which keeps the comparison honest.

---

## 4. How the code works

### Repository layout

```
EC601/
├── fuzzer/
│   ├── __main__.py   CLI entry (python -m fuzzer run ...)
│   ├── core.py       run loop, strategy, oracle, summary, save
│   ├── mutators.py   string/request mutation operators
│   └── targets.py    target registry (URL, kind, seed request, log URLs)
├── targets/
│   ├── flask_app/app.py   Site A
│   └── vuln_site/app.py   Site B
├── data/wordlists/mini.txt   uninformed dictionary
├── tests/                    test_target_flask.py, test_target_vuln.py, test_fuzzer.py
├── scripts/                  verify_dvwa.sh, verify_llm_api.py
├── docs/                     SPRINT1, TEAM, AI-Review-Logs, Faculty-List
└── results/                  run outputs (gitignored)
```

### Site A: `targets/flask_app/app.py` (POST `/submit`, JSON)

A validation chain. Each rejection has a distinct message, and only the stages **passed** are logged:

| Stage logged | Check that must pass | On failure |
|---|---|---|
| `json_ok` | body is a JSON object | 400 |
| `presence_ok` | `username` and `query` present | 400 |
| `email_ok` | username is a string matching `user@domain.tld` | 400 |
| `blacklist_ok` | local part not in reserved set (`admin`, `root`, ...) | 403 |
| `length_ok` | local part is 5–50 characters | 400 |
| `query_ok` | query is a string, ≥ 10 chars, no banned tokens (case-insensitive WAF) | 400 / 403 |
| `prefix_ok` | query starts with the secret prefix `SEARCH:` | 400 |
| `sink_reached` | (the sink) | planted bug: a `'` in the query returns **500** |

- **depth** = number of entries in `stages_passed`. It is 8 at the sink (the sink counts as an entry, so don't write "7 stages, depth 7").
- The unmutated seed (`alice@example.com`, `hello world`) reaches **depth 6** and fails at the prefix stage. So the baseline starts one stage short of the sink and must discover `SEARCH:` by itself.
- **Design decision (frozen):** the stage-7 error message says `Query must look like <OPERATION>:<argument>`. It hints at the format but does not reveal the literal prefix.
- Every response carries `X-Correlation-ID`; every request appends one JSON line to `server_log.jsonl` (gitignored).
- `GET /logs` returns the log; `POST /reset` clears it. The fuzzer calls `/reset` at the start of each run.

### Site B: `targets/vuln_site/app.py` (GET `/search?q=...&limit=...`)

- Builds SQL by **string concatenation** over an in-memory SQLite table: `... WHERE name LIKE '%{q}%' LIMIT {limit}`.
- `limit` must be digits (else 400). `q` is unvalidated, so a quote produces a real `sqlite3.OperationalError` and a **500**.
- It is a genuinely injectable endpoint (a test confirms a `UNION SELECT` returns injected rows), so the 500s are natural bugs, not a hardcoded trigger.
- Stages logged: `q_present`, `limit_ok`, `sql_attempted`, `sql_ok`. Max depth is 4.
- Same correlation-ID header, `/logs`, and `/reset` as Site A.

### Fuzzer

**`targets.py`:** a dictionary of target configs: URL, request `kind` (`json` sends a POST body, `query` sends a GET query string), log and reset URLs, and a `seed_request`, the known-valid-ish input that mutation starts from.

**`mutators.py`:**
- `mutate_string` applies one random operation: insert, delete, flip, duplicate, truncate, insert a dictionary word, replace with a dictionary word, or substitute a boundary value (empty string, huge string, `\x00`, `../`, emoji, ...).
- `mutate_request` stacks 1–3 mutations on a copy of the seed. Each picks a random field and, with small probability, drops the field (5%) or swaps in a wrong type (5%: `None`, `0`, `[]`, `{}`, ...).
- **Known limitation:** the mutator is position-blind. A dictionary word is inserted at a random index, not prepended. See §6.

**`core.py`:**
- `BaselineStrategy` owns a `random.Random(seed)`, so the payload sequence is a pure function of the seed. Request 0 returns the unmutated seed as a **calibration request**. It ignores feedback (`observe` is a no-op), which is what makes it a baseline.
- `run()` resets the target, then sends **exactly `budget`** requests. Network errors are recorded (`status: None`), not raised. Each record stores payload, status, body prefix, body length, correlation ID, and latency.
- `client_interesting`: status ≥ 500 or the body contains an error signature (`Traceback`, `sqlite3.`, `SQL syntax`, `Exception`).
- `_join_server_log()` fetches `/logs` once, joins each record to its server-side entry by correlation ID, and sets `depth` and `sink_reached`. `new_depth` is true when a request's depth exceeds the best seen so far (request 0 is never flagged). `interesting = client_interesting OR new_depth`.
- `summarize()` computes the table in §1. `save()` writes `results/run_<target>_<strategy>_s<seed>_b<budget>.json`, containing meta, summary, and every record.

**`__main__.py`:** `python -m fuzzer run --target {flask_app|vuln_site} --budget N --seed S --wordlist PATH`. It **refuses any non-localhost target**, enforcing the allowlist promised in SPRINT1 §10 (and tested).

---

## 5. How the fuzzer interacts with the websites

Concrete walkthrough of one run against Site A:

1. **Start the sites** (separate terminals):
   ```bash
   uv run python targets/flask_app/app.py     # :5000
   uv run python targets/vuln_site/app.py     # :5001
   ```
2. **Run the fuzzer:**
   ```bash
   uv run python -m fuzzer run --target flask_app --budget 200 --seed 42
   ```
3. The fuzzer `POST`s `/reset`, clearing the server log.
4. **Request 0** (calibration) sends the seed `{"username": "alice@example.com", "query": "hello world"}`. The server passes 6 stages, rejects at the prefix stage with a 400, logs `depth: 6`, and returns the correlation ID in the header.
5. **Requests 1–199** send mutated copies, for example a username with a deleted `@` (rejected at `email_ok`, depth 2) or a query with an inserted dictionary word (still no `SEARCH:` prefix, depth 6). The fuzzer sees only status, body, and the correlation ID.
6. After the budget is spent, the fuzzer fetches `GET /logs` and joins by correlation ID. Each record gets its true `depth` and `sink_reached`, which the HTTP response alone cannot tell you.
7. The oracle marks requests interesting (5xx, error signature, or deeper than anything seen before), then the summary and JSON are written.

**Site B differs only in shape.** It sends a GET query string, and mutations to `q` often produce SQL syntax errors, which the server returns as 500 with a `sqlite3.` signature. Mutations to `limit` mostly break the integer check (a 400 at depth 1). That is why about half of its requests are 400s.

**Why correlation IDs matter:** they turn a black-box HTTP exchange into an observation with server-side ground truth. That is the project's core idea. It reconstructs the kind of feedback signal that AFL's coverage bitmap gives binary fuzzers, in a domain where none exists natively.

---

## 6. Known limitations and open items

**Metric and method caveats**

- **Single runs.** n = 1 per cell; no variance or significance.
- **Uninformed dictionary.** `mini.txt` deliberately excludes `SEARCH:`. Site A's result therefore measures "a baseline with no knowledge of the secret", which is weak by construction.
- **Position-blind mutator.** Even with `SEARCH:` in the dictionary, `dict_insert` rarely lands at index 0, so it can produce the prefix only occasionally. A fair "informed" baseline needs a `dict_prepend` operation (my rough estimate, not measured, is that the current mutator hits the sink roughly once in a few thousand requests).
- **`interesting_total` counts duplicates.** SPRINT1 says "unique interesting". Dedupe by `(status, outcome)` or error signature later.
- **Request 0 is calibration, not a finding.** `new_depth` is never true for it.
- **Wall-clock and cost** are recorded per request (latency) but not yet summarized.

**Not done this sprint**

| Item | Status |
|---|---|
| Informed-dictionary control (`informed.txt`, with and without `dict_prepend`) | not run |
| Cheapest Test report (`docs/cheapest_test_results.md`: uninformed vs informed vs 10 manual payloads) | pending |
| DVWA smoke test (`scripts/verify_dvwa.sh`) | committed; Docker Desktop was not running when first attempted, rerun and record the result |
| LLM API check (`scripts/verify_llm_api.py`) | committed, **not run**; waiting on the instructor-provided key |
| SecLists wordlist | not yet used |
| `compare` command, ML and LLM strategies, 30-run statistics | Sprint 2 and 3 |

---

## 7. Reproduce

```bash
uv sync
uv run pytest -q                                                   # 30 passed
uv run python targets/flask_app/app.py                             # terminal 1
uv run python targets/vuln_site/app.py                             # terminal 2
uv run python -m fuzzer run --target flask_app --budget 200 --seed 42
uv run python -m fuzzer run --target vuln_site --budget 200 --seed 42
```

Running the same command with the same seed gives the same payload sequence. Correlation IDs and latencies differ between runs because they are generated per request.

---

## 8. Next steps

1. Run the informed-dictionary control on Site A (budget 1000), first with the current mutator, then with `dict_prepend`. Report all numbers, including a negative result.
2. Write `docs/cheapest_test_results.md` with uninformed baseline, informed baseline, and 10 hand-written payloads against Site A.
3. Finish the SPRINT1.md edits: LLM bullet wording, Site B in §4, the httpx "sync for baseline" note, cost and limit notes per tool, and the four design decisions above.
4. Run `verify_dvwa.sh` once Docker Desktop is up.
5. Sprint 2: the ML prioritizer behind the same `Strategy` interface, plus the multi-seed runner and a `compare` command.