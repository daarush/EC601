import argparse
from pathlib import Path
from urllib.parse import urlparse
from .core import BaselineStrategy, run, save, summarize
from .targets import TARGETS

def main():
    p = argparse.ArgumentParser(prog="fuzzer")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--target", choices=list(TARGETS), required=True)
    r.add_argument("--budget", type=int, default=1000)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--wordlist", default="data/wordlists/mini.txt")
    a = p.parse_args()

    t = TARGETS[a.target]
    if urlparse(t["url"]).hostname not in {"127.0.0.1", "localhost"}:   # SPRINT1 §10 allowlist
        raise SystemExit("Refusing non-local target.")
    words = [w for w in Path(a.wordlist).read_text(encoding="utf-8").splitlines() if w]
    strat = BaselineStrategy(t["seed_request"], words, a.seed)
    records = run(t, strat, a.budget)
    print(save(records, a.target, strat.name, a.seed, a.budget))
    print(summarize(records))

if __name__ == "__main__":
    main()