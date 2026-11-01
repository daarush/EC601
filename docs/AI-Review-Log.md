# AI Review Log (Sprint 1 plan)

**Plan reviewed:** the Sprint 1 plan in [SPRINT1.md](SPRINT1.md), plus the project proposal and plan documents.

**Two different models, same plan:**

- Qwen 3.8-Max: https://chat.qwen.ai/s/1c32149b-52e4-4285-be38-acdbf37f114b?fev=0.3.12
- Claude Sonnet 5.5: https://claude.ai/share/3e5e90b5-2cb9-463e-a332-4dfee8e2e6b4

Qwen answered as a free-form strengths/weaknesses "deep dive" rather than in the three-question format, so its points are mapped to the three questions below.

## Step 1: the three questions

| Question | Qwen 3.8-Max | Claude Sonnet 5.5 |
|---|---|---|
| **Riskiest unstated assumption** | The synthetic target is a fair proxy. I design it, so its difficulty may unconsciously match what mutation fuzzers struggle with ("alignment bias"). | Same root: the validation is hard in a way an LLM happens to be good at (format-awareness), not independently hard. Secondary: there are too few "interesting" events to measure. |
| **Why it might fail by week 6** | The metric saturates: with one validation chain there are only a handful of discoverable events, so thirty runs differ only in arrival time. Also: statefulness, an undefined ML feature space, LLM nondeterminism breaking reproducibility, no operational pivot. | Ceiling or floor effects (baseline wins instantly, or nothing finds anything); a target-tuning spiral that burns weeks 3 to 5; LLM cost and rate limits; too much integration surface; the LLM may recall memorized SecLists payloads instead of reasoning. |
| **Missing from the evaluation** | Defined ML features with ablation; temperature 0 and full prompt/response logging; an operational pivot metric; error-class deduplication; effect sizes and bootstrap CIs. | A single primary metric and decision rule; ablations (feedback vs. priors, no-feedback LLM); an equal-information baseline; more validator types; a bug-level metric; a frozen, hashed target; triage evaluation; cost-normalized comparison; a sanity check on the custom target, not DVWA. |

## Step 2: cross-review

**Claude attacking and defending Qwen's critique** (done in this project conversation, checked against the repo and fresh runs):

- *Defended, with data.* The saturation claim is real. Site A has 10 outcome labels in its code; the harness can never send malformed JSON, so only about 8 are reachable, and the baseline already reaches 6 distinct outcomes in all 5 seeds. The whole informed run produced 1 "interesting" event.
- *Attacked: statefulness.* Moot here. Neither target uses sessions, auth, cookies, or CSRF, so session failure cannot be confounding the baseline.
- *Attacked: "pre-registered in spirit."* Too generous. The metric, controls, and target version were not frozen, which is exactly the gap Claude's critique names.
- *Attacked: "don't build more targets."* Partly wrong. One app with several chains is cheaper, but the chains must come from a documented validator taxonomy or they inherit the same circularity.
- *Attacked: temperature 0 as the fix.* Insufficient. API sampling and model updates still make LLM runs non-reproducible, so they must be treated as stochastic.
- *Checked Claude's critique too.* "Async httpx hides ordering effects" does not apply (the client is synchronous). "Sanity check on DVWA is weak" is right.

**Qwen's response to Claude's critique:** TODO (give Qwen the Claude critique and ask it to attack or defend it, then paste its answer here).

## Step 3: outcome

**Where they agreed** (probably real problems):
1. The target is built by the evaluator and has too few distinguishable outcomes, so the metric saturates.
2. The ML variant is underspecified. Confirmed in the code: `ml_strategy.py` rewards on `new_depth`, which is only computed after the run, so it never fires during a run and the model gets almost no learning signal on Site A.
3. LLM runs are not reproducible by seed alone, so prompts, model version, and raw outputs must be logged.
4. The pivot ("AI triages findings") had no metric.
5. Findings must be deduplicated by error class.

**Where they disagreed (my decision, and why):**

| Issue | Qwen | Claude | Decision |
|---|---|---|---|
| Fixing the small outcome space | Several validation chains in one app, no new targets | Vary validator types across targets; add stateful or cross-field checks | A third target with several endpoints (Qwen's cost argument), built from a documented validator taxonomy (Claude's rigor argument), added before any AI variant runs. Site A is frozen. |
| Statefulness | Avoid it; it is a separate research problem | Include at least one stateful or cross-field check | Cross-field: yes. Stateful: out of scope, because session handling would confound the AI comparison. |
| LLM reproducibility | Temperature 0 | Log temperature and model version; do not claim determinism | Both: temperature 0 and full logging, but LLM runs are still treated as stochastic and compared as distributions. |
| Headline metric | Saturation makes first-hit useless | Pick one primary metric and rule in advance | Primary is outcome coverage (distinct server-side outcomes reached, AUC over 1,000 requests); first-hit becomes secondary. |

**The one change I made to the plan because of the review:** SPRINT1.md Section 8 is now a pre-registered analysis plan instead of a list of metrics. It fixes the primary metric (outcome coverage) and a decision rule (Mann-Whitney U p < 0.05 and A12 >= 0.64, with wall-clock and cost unable to change the headline), states which signals each variant may see, adds two controls (an equal-context baseline and a no-feedback LLM), requires prompt/response/model-version logging, and freezes the targets. To make the metric measurable, the fuzzer now records the server's outcome label per request (`distinct_outcomes` in each run summary). The pivot line in Section 7 also now has a defined metric (precision@10 of ranked findings).

**Smaller edits from the same review:** the target user and mission now match the proposal (application-security engineers, not students); the `ffuf` sanity run moves from DVWA to the custom targets.

**Not adopted, and why:**
- *Stateful validators and session handling:* out of scope for this semester's question.
- *Triage-quality user study:* deferred unless the pivot triggers.
- *SecLists contamination test:* noted as a limitation; the no-feedback LLM control partly addresses it.

---

# AI Review Log (Sprint 2 implementation)

**Tool used:** Claude (Sonnet 5.5) in the claude.ai chat, with read/write access to this repo through a file tool.
Code was run and tested in a sandbox copy first, then written to the repo and re-run on the student's machine.

**What the AI produced:** `fuzzer/ml_strategy.py`, `fuzzer/features.py`, `fuzzer/bandit_strategy.py`,
`fuzzer/llm_strategy.py`, their tests, `scripts/run_matrix.py` (strategy matrix), `scripts/compare_strategies.py`,
`docs/SPRINT2.md`, `docs/CONCLUSIONS.md`.

**How it was checked:** unit tests (96 passing at the time of the 30-seed run, plus 5 added afterwards for the
comparison script); fairness tests (ML sends the same payloads as the baseline until its first fit; server-side ground
truth cannot influence any strategy); a toy-oracle test that each learner really learns; and a full experiment of
360 runs (30 seeds x 4 cells x 3 strategies) executed on the student's machine. Per-run data: `results/summary.csv`.

**Mistakes the AI made that were caught, and what changed:**
1. The original ML reward used status codes and `new_depth` (never available during a run), so on Site A every label
   was identical and the model could not learn. Replaced by a response-rarity reward. This closes Step 3, item 2 above.
2. The first bandit used the same `1/count` reward and barely beat the baseline in a toy test. Switched to a binary
   "new or rarer than average" reward, which then passed.
3. An early 30-seed run in the AI's sandbox (seeds 1-30) suggested the bandit helped on Site A `informed` (p=0.025).
   It did not replicate on seeds 42-71 (p=0.84), so the claim was retracted. Lesson: do not trust one seed set.
4. The AI first compared final outcome counts, not the pre-registered AUC metric; corrected before concluding.
5. Several docstrings claimed things the code did not do (e.g. that both ML variants share one reward); fixed.
6. Site C: the AI rebuilt `mini.txt` from memory in its sandbox, so the first freeze hash would not have matched the real
   file (Windows line endings, no final newline). Caught by re-reading the real file before committing; re-frozen from
   the real bytes. The calibration stood because the tokens were identical.
7. Site C: the AI's pre-registered prediction that the bandit would give a modest gain (A12 0.55-0.65) was wrong
   (A12 0.43 / 0.47, no effect). Recorded as wrong in `docs/SITE_C.md`, not edited.
8. Site C: the SQL error text initially lacked the `sqlite3.` module prefix that Site B's errors have; found by a test
   and fixed in the server (before the freeze), not in the test.
9. A post-hoc pooled analysis (ML possibly slower to first interesting response, p=0.050) was run after seeing the data;
   it is labelled exploratory/hypothesis-only everywhere it appears.

**Result:** no evidence that either ML variant helps on the pre-registered primary metric (outcome-coverage AUC);
clear gains on payload correctness and yield. See `docs/SPRINT2.md` and `docs/CONCLUSIONS.md`.

**Open items (honest deviations):**
- The third target (Section 8) was built late: Sites A and B were evaluated first. Site C was calibrated on the baseline
  only, frozen (hash-checked by `tests/test_site_c_frozen.py`) and run with written predictions. Result: it confirmed the null.
- Windows port exhaustion (WinError 10048) interrupted the Site C bandit runs; the runner now retries and has `--resume`.
- The LLM variant is tested offline only; no real API run yet. The client uses the Anthropic API although the plan
  lists OpenAI; reconcile one or the other.
- Qwen's response to the Sprint 1 cross-review is still TODO (see Step 2).