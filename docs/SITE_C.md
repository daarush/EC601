# Site C ("shop"): a harder, more realistic target

**Status: FROZEN on 2026-10-30, before any ML / bandit / LLM variant was run on it.**
(Only the baseline fuzzer touched Site C, for calibration. A tiny 80-request plumbing smoke test of the ML and bandit
code paths was run to check that nothing crashes; its results were not examined.)

**Git caveat (honesty note):** the freeze record and these predictions were committed to git *after* the experiment runs, not before
(the planned pre-run commit was skipped). The repository history therefore cannot prove the order of events; it rests on the
author's account that both were written to disk before any ML/bandit run on Site C. What the hashes do show is that the design
files match the freeze record (`tests/test_site_c_frozen.py`).

## Why Site C exists
Sprint 2's null result on the primary metric is partly a measurement limit: Site A `mini` is capped by the mutator,
and Site B's bug is found by the baseline within ~65 requests. Neither leaves room for a better strategy to show a
difference. Site C is built so the baseline *can* make progress but *cannot* finish.

## What it is
A small checkout API, `POST /checkout` on port 5002 (`targets/shop_site/app.py`). Eight JSON fields:
`email, country, postal_code, quantity, shipping, coupon, note, sig`. A strategy sees only status code and body.
The server logs, per request, the stages passed, the depth and an outcome label (ground truth, never shown).

Validation chain (each stage has its own realistic error message and its own outcome label):
`json -> presence -> types -> email -> country -> postal code (format DEPENDS on country) -> quantity (1-99)
-> shipping (standard|express) -> coupon -> delivery -> signature -> note length -> database insert`.

### Planted bugs (ground truth)
| Outcome | HTTP | Trigger | Who should be able to find it |
|---|---|---|---|
| `sqli_error` | 500 | a quote in `note` or `email` reaches a string-concatenated INSERT | any mutator (a generic `'` token) |
| `coupon_parser_crash` | 500 | coupon `SAVE` with no digits (e.g. `SAVE`, `SAVEX`) | needs the token `SAVE`; the error message shows `SAVE10` |
| `express_zero_division` | 500 | `shipping=express` AND `quantity=10` | needs two specific values; messages reveal `express` and the 1-99 range |
| `premium_crash` | 500 | a valid HMAC `sig` | **nobody**: this is a TRIPWIRE. If any run triggers it, a strategy is leaking and results are void. |

16 outcomes are reachable by a JSON-dict mutator (13 rejections/successes, 3 crash bugs counting `sqli_error`);
`malformed_json`, `not_object` and `premium_crash` cannot be produced by the harness without the secret.

## Calibration (baseline only, 10 seeds x 1000 requests)
Target: the baseline should find roughly 40-80% of the reachable outcomes, not 0% and not 100%.

| | `mini` wordlist | `shop_docs` wordlist |
|---|---|---|
| Reachable outcomes found per run (of 16) | mean **11.2** (range 11-12) | mean **11.3** (range 10-12) |
| `sqli_error` found (runs of 10) | 8 | 6 |
| `note_too_long` found | 4 | 4 |
| `unknown_coupon` found | 0 | 3 |
| `coupon_out_of_range`, `coupon_parser_crash`, `express_zero_division` | 0, 0, 0 | 0, 0, 0 |
| First interesting response (request #) | 186-605; never in 2/10 runs | 184-706; never in 4/10 runs |
| Tripwire / unexpected exceptions | none | none |

So the baseline sits at about 70% of the reachable outcomes with 4-5 outcomes beyond its reach, and its time to
first interesting response (median ~320-365) is several times Site B's (~64). That is the headroom we wanted.

`shop_docs` = the generic `mini` tokens plus what a tester could copy from public API docs
(`GB DE express standard SAVE10 VIP20 10 99 "SW1A 1AA" 10115`). It deliberately does NOT contain `SAVE` alone.

## Freeze
`docs/site_c.freeze.json` stores SHA-256 hashes (line endings normalised) of `targets/shop_site/app.py`,
`data/wordlists/mini.txt`, `data/wordlists/shop_docs.txt` and the `shop` entry in `fuzzer/targets.py`.
`tests/test_site_c_frozen.py` fails if any of them changes. Check manually with
`uv run python scripts/freeze_check.py`. Re-freezing (`--update`) is a deliberate act that voids earlier Site C results.

## Pre-registered predictions (written before any variant ran on Site C; my own estimates, not data)
Protocol is unchanged from Sprint 2: 1000 requests, seeds 42-71, wordlists `mini` and `shop_docs`, primary metric
outcome-coverage AUC, a variant "helps" only if Mann-Whitney p < 0.05 AND A12 >= 0.64.

1. **Tripwire:** `premium_crash` is triggered in **0 runs for every strategy**. Anything else voids the target.
2. **Baseline (30 seeds):** finds about 10-12 of 16 reachable outcomes and triggers `coupon_parser_crash` and
   `express_zero_division` in at most 1 of 30 runs each.
3. **ML scorer:** most likely "no evidence" on the primary metric (about 25% chance of "helps"). Expect a higher
   share of requests reaching the database insert, as on Sites A and B.
4. **Bandit:** modest effect, A12 about 0.55-0.65 (about 35% chance of "helps"), because it can learn to avoid
   dead-end fields such as `sig`.
5. **LLM (Sprint 3):** most likely to help (about 70%), triggering `coupon_parser_crash` in at least half of runs
   (the error message hands it `SAVE10`) and `express_zero_division` in a minority (it must also guess quantity 10).

How to read the outcomes: if ML or bandit helps here, Sprint 2's null on Sites A and B was a headroom artifact.
If neither helps even with headroom, the null stands and is stronger. If the tripwire fires, discard everything.

## Limitations (say these in the report)
- Site C is synthetic and was designed by the same people building the strategies. Its token-gated bugs favour a
  strategy that can read error messages (the LLM) over one that only reshuffles mutations; that is a design
  choice, made visible here rather than hidden. Calibrating on the baseline alone limits, but does not remove, this bias.
- Only three gated outcomes, so a bug-level comparison has little statistical power; the AUC metric is the primary test.
- One endpoint, one session: no cross-request state (logins, carts), which real applications have.

## How to run it
```
uv run python targets/shop_site/app.py                 # terminal 1 (port 5002)
uv run python scripts/freeze_check.py                  # must say "frozen and unchanged"
uv run python scripts/run_matrix.py --targets shop --strategies baseline ml bandit --seeds $(seq 42 71)
uv run python scripts/compare_strategies.py --csv results/summary.csv > results/compare.txt
```
The comparison prints the usual tables, the pre-registered DECISION block, and a PLANTED BUGS TRIGGERED table
(runs that triggered each bug, per strategy, with the tripwire flagged).

---

## Results (added AFTER the run; the predictions above were not edited)

180 runs: 30 seeds (42-71) x 2 wordlists x 3 strategies. Per-run data: `results/summary.csv`; full tables: `results/compare.txt`.

| # | Prediction | What happened |
|---|---|---|
| 1 | Tripwire (`premium_crash`) triggered in 0 runs | **Confirmed**: 0/60 for baseline, ML and bandit. Site C is valid. |
| 2 | Baseline finds ~10-12 of 16 outcomes; the two token-gated crashes in <= 1/30 runs | **Confirmed**: 11.6 and 11.7 outcomes (mini / shop_docs); `coupon_parser_crash` 0/60, `express_zero_division` 0/60. |
| 3 | ML: most likely no evidence on the primary metric; more requests reach the DB insert | **Confirmed**: outcome AUC A12 0.43 / 0.43 (p = 0.37 / 0.39). Requests reaching the insert: 104 -> 177 per run (mini) and 106 -> 144 (shop_docs), both p < 0.001. |
| 4 | Bandit: modest effect, A12 about 0.55-0.65 | **Wrong**: AUC A12 0.43 / 0.47 (no evidence), and no change in requests reaching the insert (p = 0.16 / 0.66). |
| 5 | LLM most likely to help | Not run yet (Sprint 3). |

Totals over 60 runs (60,000 requests) per strategy:

| | Baseline | ML | Bandit |
|---|---|---|---|
| Requests that reached the database insert | 6,313 | **9,632** | 6,507 |
| Runs that triggered the SQL injection | 50 / 60 | 48 / 60 | 48 / 60 |
| Runs that triggered `coupon_parser_crash` | 0 / 60 | 0 / 60 | 0 / 60 |
| Runs that triggered `express_zero_division` | 0 / 60 | 1 / 60 | 0 / 60 |
| Kinds of server behaviour found (avg, of 16 reachable) | 11.6 | 11.6 | 11.6 |
| Pre-registered verdict (outcome AUC) | - | no evidence | no evidence |

### Reading
- **The Sprint 2 null was not just a headroom artifact.** Site C was built so the baseline could not finish (it reaches ~70% of
  the outcomes), yet neither learner found more outcomes or found them sooner. The null on the primary metric is now
  replicated on a target designed to detect an effect.
- **The token-gated bugs stayed out of reach for both learners** (`coupon_parser_crash` 0/60 each; `express_zero_division`
  1/60 for ML). They reshuffle the mutator's and wordlist's tokens; they cannot invent `SAVE` or pick `express` + `10`.
  That is exactly the gap the LLM variant (Sprint 3) is meant to test.
- **ML again trades coverage for yield**: ~50% more requests reach the database, but not more kinds of behaviour.
- **The bandit prediction was wrong.** I expected it to learn to avoid dead-end fields; it did not measurably help.
- **Exploratory, post-hoc, NOT pre-registered (hypothesis only):** pooling the six cells with a Stouffer combination, ML's
  outcome AUC is at or below the baseline's in every cell (pooled p = 0.077) and its time to first interesting response is
  later in 4 of 5 cells (pooled p = 0.050). With four such looks and no correction, treat this as a hypothesis for
  Sprint 3 (ML's rarity reward may favour re-finding rare responses over exploring), not as a finding. Bandit: nothing (p = 0.71, 0.92).
