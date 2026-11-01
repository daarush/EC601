# Documentation index

Start with **CONCLUSIONS.md** for the plain-language results, then the sprint reports for detail.

| File | What it is |
|---|---|
| `CONCLUSIONS.md` | Running summary across sprints: "base fuzzer found X, ML variants found Y", per target. Sprint 3 column left blank. |
| `SPRINT1.md` | Sprint 1: the baseline fuzzer, the two original targets (Sites A and B), the experiment design, and the **pre-registered metric and decision rule** (sections 7-8). |
| `SPRINT2.md` | Sprint 2: the two from-scratch learning variants (ML scorer, bandit) vs the baseline on Sites A, B and C. Results, interpretation, deviations. |
| `SITE_C.md` | Site C ("shop"): design, planted bugs, baseline calibration, freeze, **predictions written before the run**, and the results scored against them. |
| `site_c.freeze.json` | SHA-256 hashes of everything that defines Site C. A test fails if any of it changes after the freeze. |
| `AI-Review-Log.md` | Cross-review of the Sprint 1 plan, plus the Sprint 2 log of AI-assisted work (what was produced, checked, and got wrong). |
| `TEAM.md`, `Faculty-List.md` | Course administration. |
| `figures/` | `fig1-fig4`: Sprint 1 (`scripts/make_figures.py`). `fig5-fig8`: Sprint 2 (`scripts/make_figures_sprint2.py`). |

## Reproducing the results
```
# targets (one terminal each)
uv run python targets/flask_app/app.py        # Site A, port 5000
uv run python targets/vuln_site/app.py        # Site B, port 5001
uv run python targets/shop_site/app.py        # Site C, port 5002

uv run pytest -q                                                                  # tests
uv run python scripts/freeze_check.py                                             # Site C unchanged since the freeze
uv run python scripts/run_matrix.py --strategies baseline ml bandit --seeds $(seq 42 71) --resume
uv run python scripts/compare_strategies.py --csv results/summary.csv > results/compare.txt
uv run --with matplotlib --with pandas python scripts/make_figures_sprint2.py     # fig5-fig8
uv run --with matplotlib python scripts/make_figures.py                           # fig1-fig4 (Sprint 1 data only)
```
The raw run files (`results/matrix/`, about 180 MB) are not committed; `results/summary.csv` holds one small row per run.

## Not yet done
The LLM variant (`fuzzer/llm_strategy.py`) is built and tested offline but has not been run against a real API (Sprint 3).
