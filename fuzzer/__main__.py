import argparse
from pathlib import Path
from urllib.parse import urlparse
from .core import BaselineStrategy, run, save, summarize
from .targets import TARGETS

STRATEGY_NAMES = ["baseline", "ml"]


def load_strategy(name):
    """Return the strategy class. The ML strategy (Sprint 2) is imported lazily so the baseline
    CLI works in a checkout that does not include it."""
    if name == "ml":
        try:
            from .ml_strategy import MLStrategy
        except ModuleNotFoundError as e:
            if (e.name or "").endswith("ml_strategy"):
                raise SystemExit("The 'ml' strategy is Sprint 2 work and is not in this checkout.")
            raise
        return MLStrategy
    return BaselineStrategy


def main():
    p = argparse.ArgumentParser(prog="fuzzer")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--target", choices=list(TARGETS), required=True)
    r.add_argument(
        "--strategy",
        choices=STRATEGY_NAMES,
        default="baseline",
        help="Fuzzing strategy (default: baseline)",
    )
    r.add_argument("--budget", type=int, default=1000)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--wordlist", default="data/wordlists/mini.txt")
    r.add_argument("--out-dir", default="results", help="Where to write the run JSON (default: results)")
    a = p.parse_args()

    t = TARGETS[a.target]
    if urlparse(t["url"]).hostname not in {"127.0.0.1", "localhost"}:   # SPRINT1 §10 allowlist
        raise SystemExit("Refusing non-local target.")
    words = [w for w in Path(a.wordlist).read_text(encoding="utf-8").splitlines() if w]
    strat = load_strategy(a.strategy)(t["seed_request"], words, a.seed)
    records = run(t, strat, a.budget)
    print(save(records, a.target, strat.name, a.seed, a.budget,
               wordlist=Path(a.wordlist).stem, out_dir=a.out_dir))
    print(summarize(records))

if __name__ == "__main__":
    main()
