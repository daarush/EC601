# Conclusions (running summary across sprints)

Plain-language results. Details and statistics: `docs/SPRINT1.md`, `docs/SPRINT2.md`, `results/compare.txt`.
All numbers below come from `results/summary.csv` (30 runs per cell, 1,000 requests per run, seeds 42-71).

**The two fuzzers being compared**
- **Sprint 1: base fuzzer** - random mutations plus a wordlist. No learning. (The baseline code is unchanged, so
  re-running it over 30 seeds is the same fuzzer as Sprint 1.)
- **Sprint 2: ML variants** - same mutations, but they *learn during the run* what works.
  `ml` = a gradient-boosting model picks the most promising payload. `bandit` = learns which mutation types pay off.
- **Sprint 3: LLM variant** - TODO.

---

## The one-paragraph answer

Over 120 runs per fuzzer, the base fuzzer caused **445** bug-triggering server errors, the ML model caused
**4,289**, and the bandit caused **613**. Almost all of that difference is the ML model hitting the *same* known
bug on Site B over and over. On the question that matters more, *finding things the base fuzzer cannot*, the gain is
small: Site A's hidden server error was triggered by the base fuzzer in **0 of 90** runs, by the ML model in
**5 of 90**, and by the bandit in **1 of 90**. None of the variants discovered more *kinds* of server behaviour than
the base fuzzer.

---

## Site B: a real SQL injection (30 runs x 1,000 requests)

| | Base fuzzer (Sprint 1) | ML model (Sprint 2) | Bandit (Sprint 2) |
|---|---|---|---|
| Runs that found the SQL injection | **30 / 30** | **30 / 30** | **30 / 30** |
| Total requests that triggered it (HTTP 500) | 445 | **4,280** | 612 |
| Total requests that reached the database code | 14,726 | **21,425** | **21,508** |
| Kinds of server behaviour found (avg per run) | 4 | 4 | 4 |

Plain reading: everyone finds this bug every time. The ML variants just reach the vulnerable code more often
(about 49% of requests for the base fuzzer vs 71-72% for ML and bandit), and the ML model triggers the error about
10x as often. It is the same bug repeated, not 10x more bugs.

## Site A: a hidden server error behind a chain of input checks (90 runs: 3 wordlists x 30)

| | Base fuzzer (Sprint 1) | ML model (Sprint 2) | Bandit (Sprint 2) |
|---|---|---|---|
| Runs that triggered the hidden server error (HTTP 500) | **0 / 90** | **5 / 90** | **1 / 90** |
| Total requests that reached the vulnerable code | 313 | **2,617** | 382 |
| Runs that reached the vulnerable code at least once | 40 / 90 | 37 / 90 | 48 / 90 |
| Kinds of server behaviour found (avg per run) | 6.4 | 6.4 | 6.5 |

All five ML successes (and the bandit's one) were on the `informed` wordlist (the one that already contains the
`SEARCH:` token). With `mini` (no hints) nobody got past the first checks, and with `mini_token` nobody triggered
the error. The ML model's 5/30 is borderline (p = 0.052), so treat it as promising, not proven.

---

## Sprint 1 -> Sprint 2 in four sentences

1. **Same bugs found.** Every bug the base fuzzer found, the ML variants also found. Nothing was lost.
2. **Far more hits on the bugs it already finds.** ML turns 445 error-triggering requests into 4,289 (about 10x),
   and 15,039 vulnerable-code requests into 24,042.
3. **A small gain on the hidden bug.** The base fuzzer never triggered Site A's error; the ML model did in 5 of 30
   `informed` runs.
4. **No gain in variety or speed.** Same number of kinds of server behaviour, and the pre-registered primary test
   (outcome coverage over time) found **no evidence** that either variant helps, in any cell.

## What we can and cannot claim

- **Can claim:** the learned variants send more *valid, bug-reaching* requests, and the ML model occasionally gets
  past a check the base fuzzer never does.
- **Cannot claim:** that they find *more kinds* of bugs or find them *faster*. The data shows no such effect.
- **Why the null result may be partly a test problem:** Site A with no hints is impossible for any variant that only
  reshuffles a fixed mutator and wordlist, and Site B's bug is found within about 65 requests even by the base fuzzer.
  Both targets leave little room to show a difference. A harder third target is planned for Sprint 3.

---

## Sprint 3 (to fill in)

| | Base fuzzer | ML model | Bandit | LLM variant |
|---|---|---|---|---|
| Site A: runs that triggered the hidden error | 0 / 90 | 5 / 90 | 1 / 90 | _tbd_ |
| Site B: requests that triggered the SQL error | 445 | 4,280 | 612 | _tbd_ |
| Cost per run (API tokens) | none | none | none | _tbd_ |

Rerun with: `uv run python scripts/run_matrix.py --strategies baseline ml bandit llm --seeds $(seq 42 71)`
(the LLM needs `ANTHROPIC_API_KEY` and costs money; start with the small pilot in `docs/SPRINT2.md`, section 6).
Then `uv run python scripts/compare_strategies.py --csv results/summary.csv > results/compare.txt`.
