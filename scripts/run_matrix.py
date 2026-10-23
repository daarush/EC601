"""run_matrix.py - clean baseline matrix: every wordlist at the SAME budget, several seeds.

Start both targets first (two terminals):
    uv run python targets/flask_app/app.py
    uv run python targets/vuln_site/app.py
Then:
    uv run python scripts/run_matrix.py                    # 1000 requests x seeds 42-46
    uv run python scripts/summarize_results.py results/matrix

Wordlists (data/wordlists/):
    mini        generic attack tokens, no knowledge of the target
    mini_token  mini + ONE extra line, the secret "SEARCH:" token  (the clean "informed" control)
    informed    legacy Sprint 1 list: smaller, different entries, includes SEARCH:hello
Output goes to results/matrix/ so the Sprint 1 files in results/ are untouched.
"""
import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, so `fuzzer` imports

from fuzzer.core import BaselineStrategy, run, save, summarize
from fuzzer.targets import TARGETS

MATRIX = {
    "flask_app": ["mini", "mini_token", "informed"],
    "vuln_site": ["mini"],
}
WORDLISTS = Path("data/wordlists")


def target_is_up(t):
    try:
        httpx.get(t["logs_url"], timeout=3.0)
        return True
    except httpx.HTTPError:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44, 45, 46])
    ap.add_argument("--out-dir", default="results/matrix")
    a = ap.parse_args()

    for name in MATRIX:
        if not target_is_up(TARGETS[name]):
            sys.exit(f"Target '{name}' is not running ({TARGETS[name]['logs_url']}). Start both targets first.")

    total = sum(len(w) for w in MATRIX.values()) * len(a.seeds)
    n = 0
    for target, wordlists in MATRIX.items():
        for wl in wordlists:
            words = [w for w in (WORDLISTS / f"{wl}.txt").read_text(encoding="utf-8").splitlines() if w]
            for seed in a.seeds:
                n += 1
                t = TARGETS[target]
                strat = BaselineStrategy(t["seed_request"], words, seed)
                records = run(t, strat, a.budget)
                path = save(records, target, strat.name, seed, a.budget, wordlist=wl, out_dir=a.out_dir)
                s = summarize(records)
                print(f"[{n}/{total}] {path.name}: sink_hits={s['sink_hits']} "
                      f"first_interesting={s['first_interesting']} 500s={s['status_counts'].get(500, 0)}")


if __name__ == "__main__":
    main()
