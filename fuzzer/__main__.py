import argparse
import importlib
from pathlib import Path
from urllib.parse import urlparse
from .core import BaselineStrategy, run, save, summarize
from .targets import TARGETS

STRATEGY_NAMES = ["baseline", "ml", "bandit", "llm"]
_LAZY = {"ml": ("ml_strategy", "MLStrategy"), "bandit": ("bandit_strategy", "BanditStrategy"),
         "llm": ("llm_strategy", "LLMStrategy")}


def load_strategy(name):
    """Return the strategy class. The ML, bandit and LLM strategies are imported lazily so the baseline CLI
    works in a checkout that does not include them."""
    if name == "baseline":
        return BaselineStrategy
    module, cls = _LAZY[name]
    try:
        mod = importlib.import_module(f".{module}", package=__package__)
    except ModuleNotFoundError as e:
        if (e.name or "").endswith(module):
            raise SystemExit(f"The '{name}' strategy is not in this checkout.")
        raise
    return getattr(mod, cls)


def main():
    p = argparse.ArgumentParser(prog="fuzzer")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--target", choices=list(TARGETS), required=True)
    r.add_argument(
        "--strategy",
        choices=STRATEGY_NAMES,
        default="baseline",
        help="Fuzzing strategy (default: baseline). 'llm' needs ANTHROPIC_API_KEY and ignores --wordlist.",
    )
    r.add_argument("--budget", type=int, default=1000)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--wordlist", default="data/wordlists/mini.txt")
    r.add_argument("--out-dir", default="results", help="Where to write the run JSON (default: results)")
    a = p.parse_args()

    t = TARGETS[a.target]
    if urlparse(t["url"]).hostname not in {"127.0.0.1", "localhost"}:   # SPRINT1 §10 allowlist
        raise SystemExit("Refusing non-local target.")
    # The LLM strategy brings its own prior knowledge: it is never given the wordlist.
    words = [] if a.strategy == "llm" else \
        [w for w in Path(a.wordlist).read_text(encoding="utf-8").splitlines() if w]
    try:
        strat = load_strategy(a.strategy)(t["seed_request"], words, a.seed)
    except RuntimeError as e:
        raise SystemExit(str(e))
    records = run(t, strat, a.budget)
    wl_label = "none" if a.strategy == "llm" else Path(a.wordlist).stem
    print(save(records, a.target, strat.name, a.seed, a.budget,
               wordlist=wl_label, out_dir=a.out_dir,
               params=getattr(strat, "params", None)))
    print(summarize(records))

if __name__ == "__main__":
    main()
