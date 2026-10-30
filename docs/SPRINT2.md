# Sprint 2: Online-learning variants 

**Goal.** Build ML-assisted fuzzing strategies *from scratch* (no pretrained model) and test them against the
Sprint 1 baseline under the pre-registered protocol.

## 1. What was built

| Variant | Learns | How | Code |
|---|---|---|---|
| `ml` | which *payloads* look promising | Each turn: 20 candidate mutations (the baseline mutator), a gradient-boosting regressor scores them, the best is sent. Trained online on `(payload features -> response rarity)`. Per-field, validity-aware features. 10% random exploration. | `fuzzer/ml_strategy.py`, `fuzzer/features.py` |
| `bandit` | which *mutations* pay off | Thompson sampling over (field, operator) arms with a Beta posterior each. Same mutation primitives and 1-3 stacking as the baseline. No features, no sklearn. | `fuzzer/bandit_strategy.py` |

Both start with no knowledge and learn only from the target's responses during the run. Both use **client-visible
data only** (status code, response body, payload); server-side ground truth is never an input (asserted by tests).
Reward = response *rarity* (ML: `1/count` of a response signature; bandit: binary "new or rarer than the average
kind"). The bandit's reward differs because `1/count` made it indistinguishable from the baseline in testing.

Fairness properties, all covered by tests: until its first fit the ML variant sends exactly the same payloads as
the baseline for the same seed; every variant spends the same request budget; hyperparameters are saved in each
run's `meta.params`.

## 2. Evaluation protocol (as pre-registered in SPRINT1.md, section 8)

- Targets and wordlists: `flask_app` (Site A) x {`mini`, `mini_token`, `informed`}, `vuln_site` (Site B) x {`mini`}.
- 1000 requests per run, **30 seeds (42-71)**, 360 runs total. Same seeds across strategies.
- **Primary metric: outcome-coverage AUC** (mean number of distinct server outcomes seen after each request).
- Rule: a variant "helps" only if Mann-Whitney p < 0.05 **and** Vargha-Delaney A12 >= 0.64.
- Secondary / descriptive: final distinct outcomes, requests-to-first-interesting (censored at budget + 1),
  `sink_hits` (requests that reached the vulnerable code; a payload-correctness proxy), interesting responses,
  and whether the planted bug (HTTP 500) was triggered in a run.
- Reproduce: `uv run python scripts/run_matrix.py --strategies baseline ml bandit --seeds $(seq 42 71)` then
  `uv run python scripts/compare_strategies.py --csv results/summary.csv > results/compare.txt`.

## 3. Results (means over 30 seeds; full table in `results/compare.txt`, per-run data in `results/summary.csv`)

**Primary metric: no variant helps in any cell.**

| Cell | outcome AUC: baseline | ML | bandit | Verdict (both) |
|---|---|---|---|---|
| Site A / mini | 5.78 | 5.76 | 5.82 | no evidence |
| Site A / mini_token | 6.00 | 5.90 | 6.17 | no evidence |
| Site A / informed | 6.68 | 6.70 | 6.53 | no evidence |
| Site B / mini | 3.90 | 3.86 | 3.91 | no evidence |

**Secondary metrics.**

| Cell / metric | baseline | ML | bandit |
|---|---|---|---|
| Site A informed: requests reaching the sink (of 1000) | 10.0 | **86.1** (p<0.001) | 11.9 (n.s.) |
| Site B: requests reaching the sink (of 1000) | 490.9 | **714.2** (p<0.001) | **716.9** (p<0.001) |
| Site B: interesting responses per run | 14.8 | **142.7** (p<0.001) | 20.4 (p=0.045) |
| Site A informed: runs that triggered the planted 500 | 0/30 | 5/30 (Fisher p=0.052) | 1/30 (n.s.) |
| Site A informed: requests to first interesting (median) | 62.5 | 101.5 (p=0.13, n.s.) | 68.0 (n.s.) |

## 4. Interpretation

1. **Both learned models make a larger share of requests reach application logic** (payload correctness on Site B
   about 49% -> 71%; on Site A `informed` ML 1% -> 8.6%). This replicated across two independent seed sets.
2. **They do not discover more kinds of behaviour or discover it sooner.** Outcome coverage is capped by the
   mutator and wordlist (Site A `mini` cannot reach the `SEARCH:` stage whatever the learner does).
3. **"More interesting responses" on Site B is mostly repetition** of the same SQL error (distinct outcomes are
   identical), so it is a confirmation yield, not more findings.
4. ML may be *slower* to its first interesting response on Site A `informed` (not significant; same direction in an
   earlier independent seed set). Untested hypothesis: after warmup it chases rare responses rather than new depth.
5. Pivot rule (SPRINT1.md section 7): ML triggered Site A's planted bug in 5/30 `informed` runs vs 0/30 for the
   baseline, borderline (p=0.052). Not triggered on `mini` / `mini_token` for any variant.

## 5. Deviations and limitations 

- **Third target not built before running the AI variants** (section 8 required it). Results are on frozen Sites A and B.
- **Little headroom on the primary metric:** Site A `mini` is capped by the mutator; on Site B the baseline already
  reaches its first interesting response by about request 64. A null result here is partly a measurement limit.
- No multiple-comparison correction: 40 tests were run in the full table, so isolated p~0.04 results (e.g. bandit on
  `mini_token`) should be treated as noise. An earlier seed set did not replicate them.
- The LLM variant exists (`fuzzer/llm_strategy.py`, tested offline) but has **not** been run against a real API;
  that is Sprint 3. The client uses the Anthropic API (SPRINT1.md lists OpenAI; update one or the other).
- AI-assisted development: code and analysis were produced with an AI assistant and checked by tests and by running
  the experiments; record this in `docs/AI-Review-Log.md`.

## 6. Next (Sprint 3)

1. Build the third target (deeper validation chain) so the primary metric can discriminate, then rerun all variants.
2. Pilot, then run, the LLM variant (`--strategies llm`); report its token/latency cost beside any gain.
3. Optional: ML feature ablation and a bandit/ML hybrid.
