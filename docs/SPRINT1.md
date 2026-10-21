# AI-Assisted Web Fuzzing: Sprint 1 Plan and Results

Aarush Duvvuri · EC 601 · Solo project · Board: [Project Board](https://github.com/users/daarush/projects/2) · Related: [TEAM.md](TEAM.md), [AI-Review-Log.md](AI-Review-Log.md), [Faculty-List.md](Faculty-List.md)

**Sprint 1 at a glance.** Built a modular baseline fuzzer and two instrumented Flask targets (Site A: hard, Site B: easy), then ran the riskiest-assumption test. Result: the baseline never reaches Site A's vulnerable code (0/1000 requests), a human does 10/10, and the baseline finds real bugs on Site B. The premise holds, so Sprint 2 (ML) can start. Caveats are in Section 7.

## 1. Mission

> For security engineers and students who want to know whether AI actually improves web fuzzing, this project builds a modular Python HTTP fuzzer and compares a mutation baseline against a learned prioritizer and an LLM-guided payload generator, measured by interestingness per fixed budget (requests, wall-clock, cost) and payload validation-pass rate on an instrumented Flask target with server-side ground truth.

This is a best guess, not final. The Sprint 1 test below (Section 7) is what it was checked against.

## 2. Target User

A security-literate developer or graduate student deciding whether an AI layer on a basic web fuzzer is worth the integration cost. They can run a Python script, read a JSON report, and interpret a comparison table. They do not need to train a model or write prompts: the tool and report should speak for themselves.

## 3. User Stories (top 5)

Each story is an issue on the board (EC601 #1 to #5). Status as of the Sprint 1 review; the board is the source of truth.

| # | Story | Acceptance criteria | Status |
|---|---|---|---|
| 1 | As a researcher, I run the baseline fuzzer at a fixed request budget and get a structured JSON log of every request and response. | `uv run python -m fuzzer run --target flask_app --budget 1000 --seed 42` writes `results/run_<target>_<strategy>_s<seed>_b<budget>.json`. | Done |
| 2 | As a researcher, I inspect the target's server-side log to see which validation stage each payload reached. | Every request's correlation ID joins to a server log entry with stages passed, depth, and sink reachability. | In review |
| 3 | As a researcher, I use a CLI harness that enforces the budget, the random seed, and a target reset. | Same seed gives an identical payload sequence; the run stops at exactly the budget; non-localhost targets are refused. | In review |
| 4 | As a researcher, I run the "cheapest test" to show the target is hard for the baseline but solvable. | `scripts/cheapest_test.py` sends 10 hand-written payloads and reports sink-reach vs. the baseline's rate. | Done |
| 5 | As a researcher, I reproduce the environment on a new machine with one command. | `uv sync` installs everything from `uv.lock`; `uv run pytest -q` passes. | In review |

## 4. Feasibility (show, don't tell)

| Item | Proof in the repo | Status |
|---|---|---|
| Environment | `pyproject.toml`, `uv.lock`, `.env.example` | Works on my machine; fresh-clone test still to do |
| Site A (hard target) | `targets/flask_app/`: 7 validation checks, a sink, correlation-ID middleware, `/logs`, `/reset` | Running |
| Site B (easy target) | `targets/vuln_site/`: almost no validation, real SQL injection | Running |
| Fuzzer core | `fuzzer/`: strategy interface, exact-budget loop, JSON logger, localhost allowlist | 64 unit tests passing (`uv run pytest -q`) |
| DVWA (external sanity target) | `scripts/verify_dvwa.sh` | Smoke test passed |
| LLM API | `scripts/verify_llm_api.py` | **Blocked: API key pending**, script not yet run |

## 5. Tooling

| Tool | Why |
|---|---|
| Python 3.11 + `uv` | Project language; `uv.lock` gives a one-command reproducible environment |
| Flask | Both targets; easy to instrument with per-request correlation-ID middleware |
| `httpx` (sync) | Exact-budget request loop; deterministic; network errors are recorded, never raised |
| `pytest` | Unit tests for determinism, budget, oracle, and the localhost allowlist |
| JSON flat files | One log per run; no external database |
| Docker + DVWA | Standard external target, used only as a sanity check |
| `scikit-learn` (Sprint 2) | Fast, explainable prioritizer; no GPU |
| OpenAI API + Pydantic (Sprint 3) | Batched, schema-constrained payload generation. Cost and rate limit to be recorded once the key works |
| `matplotlib` (optional) | Result figures |

Everything runs on my laptop against localhost.

## 6. Demo Sentence

> At the end of two weeks I will show the baseline mutation fuzzer and the instrumented Flask target running end to end under a fixed request budget, and the "cheapest test" showing the target's validation is hard enough to justify AI in Sprint 2.

Status: shown (Section 7).

## 7. Riskiest Assumption, Its Test, and the Result

**Assumptions:** (1) a mutation baseline with a good wordlist does not already saturate Site A; (2) "interesting" can be defined precisely enough to measure; (3) an LLM can produce valid payloads fast enough for a fair comparison; (4) response features carry enough signal for a classifier to beat random; (5) Site A is hard enough that payload correctness is non-trivial.

**Riskiest: #1.** If the baseline already finds everything, there is nothing for AI to add.

**Cheapest test (run before any AI code):** run the baseline on both targets over several seeds, add an informed-dictionary control (the wordlist is told the secret `SEARCH:` token), and send 10 hand-written payloads to Site A. The two sites differ on purpose: Site A tests intelligence, Site B tests that the fuzzer works at all.

**Terms.** *Sink*: the vulnerable code the fuzzer is trying to reach. *Depth*: how many of Site A's 8 validation stages a request passed (the server records it; the fuzzer never sees it). *Interesting*: the oracle defined in Section 8. *Informed*: the wordlist also contains the secret `SEARCH:` token.

**Result: assumption #1 held.**

| Run | Site | Requests | Reached sink | Bug (500) | First interesting |
|---|---|---|---|---|---|
| Uninformed baseline, 5 seeds | A | 5 × 200 | **0 / 1000** | 0 | none in any seed |
| Informed-dictionary control, 1 seed | A | 1000 | 12 / 1000 (1.2%) | **0** | request 33 |
| 10 manual payloads | A | 10 | **10 / 10** | 5 / 10 | n/a |
| Uninformed baseline, 5 seeds | B | 5 × 200 | 503 / 1000 (50.3%) | 12 / 1000 (1.2%) | request 22 to 104 |
| Informed-dictionary control, 1 seed | B | 1000 | 482 / 1000 | 9 / 1000 | request 115 |

![Site A vs Site B](figures/fig2_site_a_vs_b.png)

Where requests die on Site A (the baseline stalls at the `SEARCH:` prefix check, stage 7):

![Site A validation funnel](figures/fig1_site_a_funnel.png)

*Per-seed view: [`figures/fig3_per_seed.png`](figures/fig3_per_seed.png).*

- **The premise survives.** The baseline never passes Site A's `SEARCH:` check, while a human reaches the sink 10/10. Site B shows the fuzzer and oracle work: every seed found a real bug.
- **Reaching the sink is not triggering the bug.** Even with the token in the wordlist, 0 of the 12 sink-reaching payloads contained the `'` that causes the 500.
- **Caveats.** The informed control is partly leaky: 8 of its 12 sink hits were one wordlist entry (`SEARCH:hello`) that is already a complete valid query. It is also one seed at budget 1000, compared against 200-request runs, so budget and wordlist are confounded. Site A's 0/1000 is expected by design. Site B's "9 interesting" is only 2 distinct error classes (3 quote errors, 6 null-byte errors).

**Pivot line.** I pivot if, against Site A with a standard wordlist, neither the ML nor the LLM variant reaches an error class or validation stage the baseline cannot. The project then becomes "AI triages and explains findings for a human analyst" instead of "AI finds more."

## 8. Evaluation with a Baseline

- **Oracle ("interesting").** HTTP 5xx, or an error signature in the body, or server-confirmed new maximum validation depth. This is anomaly detection for triage, not confirmed exploitation.
- **Primary metric.** Interestingness over budget (area under the curve), reported for request count (1,000), wall-clock, and LLM cost. Headline: requests to first interesting response.
- **Secondary metric.** Share of payloads that pass all validation stages and reach application logic.
- **Statistics.** At least 30 seeded runs per variant per target (10 minimum if compute-bound); Mann-Whitney U for significance and Vargha-Delaney A12 for effect size, following the FuzzBench method [3].
- **Baseline.** My own mutation fuzzer (dictionary + random mutation), identical to the AI variants in everything except the intelligence layer. The baseline's cost is about 14 ms per request and no tokens.
- **Sanity reference.** DVWA smoke test now; one `ffuf` run later, as a different tool class rather than a competitor.
- **LLM design.** Generation is batched (about 50 to 100 payloads per call) and schema-constrained; tokens, latency, and dollars are logged as cost metrics.
- **Fixes before Sprint 2 comparisons.** (a) Rerun both wordlists at the same budget over 5+ seeds; (b) record the wordlist in each run's metadata and filename; (c) deduplicate findings by error class; (d) treat "no interesting response" as censored at the budget rather than dropping it.

## 9. Related Work

| # | Paper | What it does | What it leaves open for this project |
|---|---|---|---|
| 1 | Manès et al., [Art, Science, and Engineering of Fuzzing](https://ieeexplore.ieee.org/document/8863940), TSE 2021 | Unified fuzzer model and taxonomy | Little on black-box HTTP feedback loops |
| 2 | Gan et al., [CollAFL](https://www.computer.org/csdl/proceedings-article/sp/2018/435301a679/12OmNBKEyoL), S&P 2018 | Collision-free coverage feedback | Needs program CFG; a remote service gives none |
| 3 | Fioraldi et al., [Dissecting AFL](https://dl.acm.org/doi/10.1145/3580596), TOSEM 2023 | Ablates AFL design choices on FuzzBench | Native-code targets only; motivates ablating each "intelligence" choice |
| 4 | Fioraldi et al., [AFL++](https://www.usenix.org/conference/woot20/presentation/fioraldi), WOOT 2020 | Modular platform with a plugin API | Architectural model for my strategy interface; not black-box HTTP |
| 5 | Böhme et al., [Greybox Fuzzing as a Markov Chain](https://ieeexplore.ieee.org/document/8233151), TSE 2019 | Formal model of coverage-guided scheduling | Assumes coverage; web needs response-based signals |
| 6 | Ji et al., [ChatAFL](https://www.ndss-symposium.org/ndss-paper/large-language-model-guided-protocol-fuzzing/), NDSS 2024 | LLM-in-the-loop protocol fuzzing | Network protocols, not web forms; the loop is relevant to my LLM variant |
| 7 | Xia et al., [Fuzz4All](https://arxiv.org/abs/2308.04748), ICSE 2024 | LLM input generation with prompt updating | No HTTP state, schema, or response feedback |
| 8 | Hou et al., [LLMs for Cybersecurity: A Survey](https://arxiv.org/abs/2402.16968), 2024 | Landscape of LLMs in vulnerability work | A survey, not a controlled web-fuzzer benchmark |
| 9 | Godefroid et al., [Grammar-based whitebox fuzzing](https://dl.acm.org/doi/10.1145/1375581.1375607), PLDI 2008 | Grammars get inputs past early parsers | Needs whitebox access and a hand-written grammar |
| 10 | [OSS-Fuzz](https://github.com/google/oss-fuzz) / [FuzzBench](https://fuzzbench.com/) | Large-scale fuzzing and benchmarking infrastructure | Good evaluation model (fixed budgets, statistics); not black-box HTTP |

**The gap.** Nobody has run a controlled, ablated comparison of mutation vs. ML vs. LLM strategies for web fuzzing with server-side ground truth. Papers 1 to 5 supply the loop, 6 and 7 the generation idea, and this project joins them in the web domain.

## 10. Three Lines on Harm

1. Pointed at a system without authorization, the fuzzer produces attack-like traffic that can trigger incident response or cause denial of service, so it refuses any non-localhost target.
2. LLM-generated SQLi/XSS payloads could be copied into real attacks if reports are shared carelessly, so payloads are logged but reports avoid ready-to-use exploit strings.
3. A negative "AI doesn't help" result drawn from a weak target or metric could be misused to dismiss AI-assisted testing, so every finding states its scope (two local targets, one author).
