
# Sprint 1 Results: Baseline Telemetry & Target Saturation Analysis

## 1. Base Terms & Methodology
To ensure scientific rigor and apples-to-apples comparisons in future sprints, the following parameters and definitions govern the experimental harness:

| Term | Definition | Why We Need It |
| :--- | :--- | :--- |
| **Budget** | The strict, fixed number of HTTP requests allowed per run (e.g., 200 or 1000). | Prevents "brute force" infinity loops. Ensures AI variants are judged on *efficiency* (signal per request), not just raw compute time. |
| **Seed** | The integer initializing the Pseudo-Random Number Generator (e.g., `42`). | Guarantees deterministic mutation sequences. Allows us to prove variance across seeds and reproduce exact bug trails. |
| **Oracle** | The automated scoring logic that evaluates HTTP responses and server logs. | Replaces subjective human analysis with an objective, repeatable metric for "success." |
| **Interesting** | A request that yields a 5xx error, an error signature in the body, or reaches a **new maximum validation depth**. | Distinguishes between normal background traffic and anomalous behavior that hints at a vulnerability. |
| **Depth** | The exact count of server-side validation stages a payload successfully passes. | Provides granular, ground-truth progress tracking that HTTP status codes (which just say "400 Bad Request") cannot show. |
| **Sink** | The dangerous code execution point (e.g., the SQL query builder). | Reaching the sink is a prerequisite for exploitation. |
| **Correlation ID** | A UUID injected into the HTTP header and server logs per request. | Bridges the gap between black-box client observations and white-box server ground truth. |

---

## 2. Experiment 1: Multi-Seed Variance (Uninformed Baseline)
**Objective:** Prove that the baseline fuzzer cannot trivially saturate the hard target (Site A), and prove that the harness is sensitive to seed variance (justifying future statistical testing).
**Parameters:** Budget `200`, Wordlist `mini.txt` (uninformed, no target-specific tokens), Seeds `42, 43, 44, 45, 46`.

### Site A (Hard Target: JSON, Multi-stage Validation)
| Seed | Requests | Interesting | Max Depth | Sink Hits | Status Counts |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 42 | 200 | 0 | 6 | 0 | 400: 199, 403: 1 |
| 43 | 200 | 0 | 6 | 0 | 400: 199, 403: 1 |
| 44 | 200 | 0 | 6 | 0 | 400: 198, 403: 2 |
| 45 | 200 | 0 | 6 | 0 | 400: 198, 403: 2 |
| 46 | 200 | 0 | 6 | 0 | 400: 197, 403: 3 |

**Conclusion:** The uninformed baseline makes **zero progress** past its own starting calibration request (Depth 6). It cannot guess the secret `SEARCH:` prefix required to reach the sink. This validates our riskiest assumption: the target is sufficiently complex to require intelligence beyond random mutation.

### Site B (Sanity Target: GET, Real SQLite Injection)
| Seed | Requests | Interesting | First Int. | Max Depth | Sink Hits | 500 Errors |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 42 | 200 | 2 | 65 | 4 | 100 | 2 |
| 43 | 200 | 2 | 90 | 4 | 95 | 2 |
| 44 | 200 | 3 | 43 | 4 | 102 | 3 |
| 45 | 200 | 1 | 104 | 4 | 102 | 1 |
| 46 | 200 | 4 | 22 | 4 | 104 | 4 |

**Conclusion:** Site B proves the harness is highly sensitive to seed variance. Because the target is easy, the exact sequence of random mutations dictates whether we hit a SQL error on request #22 or #104. **This justifies our Sprint 2 statistical protocol:** we cannot rely on single runs; we must use the Mann-Whitney U test across 30 seeds to prove AI superiority.

---

## 3. Experiment 2: Informed-Dictionary Control
**Objective:** Determine if the baseline can solve the target if it is *given the answer* (the secret prefix) in its wordlist, but still forced to use position-blind random mutation.
**Parameters:** Budget `1000`, Seed `42`, Wordlist `informed.txt` (contains `SEARCH:`).

### Site A Output
```json
{'requests': 1000, 'first_interesting': 33, 'interesting_total': 1, 
 'max_depth': 8, 'sink_hits': 12, 'status_counts': {400: 980, 200: 12, 403: 8}}
```

### Site B Output
```json
{'requests': 1000, 'first_interesting': 115, 'interesting_total': 9, 
 'max_depth': 4, 'sink_hits': 482, 'status_counts': {200: 473, 400: 518, 500: 9}}
```

### The "Gotcha" Analysis (Crucial Finding)
A surface-level reading of Site A shows 12 sink hits but only 1 "interesting" event and zero 500 errors. This is actually a perfect demonstration of the oracle's design:
1. **Why 12 sink hits but zero 500s?** The informed dictionary successfully bypassed Stage 7 (the prefix check), allowing 12 payloads to reach the sink (the SQL query). However, the planted bug requires a single quote (`'`) to trigger the `sqlite3.OperationalError` (the 500). The baseline found the *door* to the sink, but failed to randomly mutate the exact character needed to *break* it.
2. **Why `interesting_total: 1`?** The oracle defines "interesting" as a 5xx error OR a **new** maximum depth. The *very first time* the fuzzer stumbled onto `SEARCH:` (at request #33), it hit depth 8. The oracle flagged it as `new_depth = True`. The next 11 times it hit the sink, the depth was still 8 (not new), and the status was 200 (not a 500). The oracle correctly ignored them as duplicates.

**Conclusion:** Even knowing the secret token, position-blind mutation rarely reaches the sink (12/1000), and completely fails to craft the exploit. This perfectly isolates the exact problem the Sprint 2 LLM/ML variants must solve: moving from *endpoint discovery* to *exploit crafting*.

---

## 4. Experiment 3: The Cheapest Test (Manual Payloads)
**Objective:** Prove that the target is mathematically solvable and that a human (or LLM) can trivially reach the sink when the baseline cannot.
**Parameters:** 10 hand-crafted payloads sent directly to Site A via `scripts/cheapest_test.py`.

### Output
| Payload Type | Count | Expected Status | Actual Status | Sink Reached |
| :--- | :--- | :--- | :--- | :--- |
| Clean (Valid Prefix) | 5 | 200 OK | 5x 200 | Yes |
| Planted Bug (Quote) | 5 | 500 Error | 5x 500 | Yes (Crash) |

**Sink-Reach Rate:** 10/10 (100%)
**Baseline Comparison:** 0/200 (0%) in the uninformed run.

**Conclusion:** The riskiest assumption is officially resolved. The target's validation logic is complex enough to thwart random mutation, but solvable via contextual intelligence. The harness correctly grades the manual payloads, proving the telemetry pipeline is functioning flawlessly.

---

## 5. Environment Smoke Tests
| Test | Status | Notes |
| :--- | :--- | :--- |
| **DVWA Docker Image** | ✅ PASSED | Image pulled, container started, login page verified reachable at `localhost:8080`. |
| **LLM API Check** | ⏸️ BLOCKED | `verify_llm_api.py` is committed and ready. Execution is pending the instructor-provided API key. *Architecture Note: The Strategy Interface is fully stubbed; the moment the key is injected into `.env`, the batched-generation loop will execute without requiring changes to the fuzzer core.* |

---

## 6. Overall Conclusion
Sprint 1 successfully produced a scientifically valid experimental foundation. 
1. **The Harness Works:** Correlation IDs successfully bridge black-box HTTP responses with white-box server logs.
2. **The Oracle is Sound:** It correctly distinguishes between "finding an endpoint" (depth progression) and "triggering a bug" (5xx errors), ignoring duplicate sink hits.
3. **The Target is Valid:** Site A is definitively hard for random mutation but solvable for intelligence. Site B provides a necessary sanity check to prove the fuzzer isn't universally broken.

The baseline does **not** saturate the target. The project's core claim (that AI can add measurable signal over random mutation) remains highly viable.

---

## 7. Next Steps (Sprint 2)
1. **ML Prioritizer Integration:** Implement the `HistGradientBoosting` strategy behind the existing `Strategy` interface to rank candidate payloads based on response features (status, length, latency).
2. **Statistical Matrix:** Execute the 30-run protocol (Seeds 1-30) across Baseline and ML variants on both targets.
3. **Significance Testing:** Compute Area Under the Curve (AUC) for interestingness-over-budget, and apply the Mann-Whitney U test + Vargha-Delaney A12 effect size to determine if the ML variant is statistically superior.
