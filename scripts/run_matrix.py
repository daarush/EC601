"""run_matrix.py - clean strategy matrix: every wordlist at the SAME budget, several seeds.

Start both targets first (two terminals):
    uv run python targets/flask_app/app.py
    uv run python targets/vuln_site/app.py
Then:
    uv run python scripts/run_matrix.py                              # ML only, 1000 requests x seeds 42-46
    uv run python scripts/run_matrix.py --strategies baseline ml     # re-run both (same seeds => same baseline payloads)
    uv run python scripts/run_matrix.py --seeds $(seq 42 71)         # 30 seeds (bash) for real statistics
    uv run python scripts/run_matrix.py --strategies bandit          # second ML variant (Thompson sampling), free to run
    uv run python scripts/run_matrix.py --strategies llm --seeds 42 43 44 45 46   # needs ANTHROPIC_API_KEY; costs tokens
    uv run python scripts/compare_strategies.py

The baseline results already in results/matrix are valid for comparison: the baseline is unchanged and
deterministic per seed, so by default only the ML strategy is run. Use the SAME budget and seeds for all.

The LLM strategy never sees a wordlist, so it is run ONCE per target (saved with wordlist "none") and
compared against the baseline/ML result of every wordlist. Each LLM run logs tokens, latency and the
per-call transcript under meta.params. LLM sampling is not seeded: runs are not bit-reproducible.

Wordlists (data/wordlists/):
    mini        generic attack tokens, no knowledge of the target
    mini_token  mini + ONE extra line, the secret "SEARCH:" token  (the clean "informed" control)
    informed    legacy Sprint 1 list: smaller, different entries, includes SEARCH:hello
Output goes to results/matrix/ so the Sprint 1 files in results/ are untouched.
Each ML/LLM run also records its settings under meta.params for reproducibility.
"""
import argparse
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, so `fuzzer` imports

from fuzzer.__main__ import load_strategy
from fuzzer.core import run, save, summarize
from fuzzer.targets import TARGETS

MATRIX = {
    "flask_app": ["mini", "mini_token", "informed"],
    "vuln_site": ["mini"],
}
STRATEGIES = ["baseline", "ml", "bandit", "llm"]
WORDLISTS = Path("data/wordlists")


def target_is_up(t):
    try:
        httpx.get(t["logs_url"], timeout=3.0)
        return True
    except httpx.HTTPError:
        return False


def jobs(strategies):
    """Yield (target, strategy, wordlist_label, words). The LLM is wordlist-independent: one job per target."""
    for target, wordlists in MATRIX.items():
        for strategy in strategies:
            if strategy == "llm":
                yield target, strategy, "none", []
                continue
            for wl in wordlists:
                words = [w for w in (WORDLISTS / f"{wl}.txt").read_text(encoding="utf-8").splitlines() if w]
                yield target, strategy, wl, words


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    ap.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=["ml"])
    ap.add_argument("--out-dir", default="results/matrix")
    a = ap.parse_args()

    for name in MATRIX:
        if not target_is_up(TARGETS[name]):
            sys.exit(f"Target '{name}' is not running ({TARGETS[name]['logs_url']}). Start both targets first.")
    if "llm" in a.strategies and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("The 'llm' strategy needs ANTHROPIC_API_KEY in the environment.")

    all_jobs = list(jobs(a.strategies))
    total = len(all_jobs) * len(a.seeds)
    n = 0
    for target, strategy_name, wl, words in all_jobs:
        for seed in a.seeds:
            n += 1
            t = TARGETS[target]
            strat = load_strategy(strategy_name)(t["seed_request"], words, seed)
            records = run(t, strat, a.budget)
            path = save(records, target, strat.name, seed, a.budget, wordlist=wl,
                        out_dir=a.out_dir, params=getattr(strat, "params", None))
            s = summarize(records)
            extra = ""
            if strategy_name == "llm":
                u = strat.usage
                extra = (f" llm_calls={u['calls']} tokens={u['input_tokens']}+{u['output_tokens']} "
                         f"fallbacks={u['fallback_payloads']}")
            print(f"[{n}/{total}] {path.name}: sink_hits={s['sink_hits']} "
                  f"first_interesting={s['first_interesting']} "
                  f"distinct_outcomes={s['distinct_outcomes']} 500s={s['status_counts'].get(500, 0)}{extra}")


if __name__ == "__main__":
    main()
