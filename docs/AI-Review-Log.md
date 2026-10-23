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