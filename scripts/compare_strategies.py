"""compare_strategies.py - baseline vs ML vs bandit vs LLM on the saved matrix runs.

    uv run python scripts/compare_strategies.py                 # reads results/matrix
    uv run python scripts/compare_strategies.py results/matrix
    uv run python scripts/compare_strategies.py --csv results/summary.csv   # also export one small row per run

For every (target, wordlist) cell and every non-baseline strategy it prints, per metric, the median
[mean] of both, the Vargha-Delaney A12 effect size (P(strategy > baseline); 0.5 = no difference) and the
Mann-Whitney U p-value. The LLM strategy never sees a wordlist, so its runs (saved with wordlist "none")
are compared against the baseline of every wordlist of the same target. LLM cost is reported at the end.

A DECISION block applies the pre-registered rule on outcome_auc: a variant "HELPS" only if Mann-Whitney
p < 0.05 and A12 >= 0.64 ("HURTS" if p < 0.05 and A12 <= 0.36). It also reports the bug-level view: in how
many runs the planted bug (an HTTP 500) was triggered at all, with a Fisher exact test (the pivot rule in
SPRINT1.md section 7 asks whether a variant reaches an error class the baseline cannot).

Read the metrics in this order:
  outcome_auc         PRE-REGISTERED PRIMARY METRIC (SPRINT1.md section 8): area under the discovery curve of
                      distinct server-side outcomes over the budget (mean #outcomes seen after each request;
                      higher = outcomes found earlier and more of them). Needs the per-request records.
  distinct_outcomes   do we reach MORE KINDS of server behaviour at the end of the budget?
  first_interesting   requests until the first interesting response (None => censored at budget + 1;
                      LOWER is better, so A12 < 0.5 favours the strategy here)
  sink_hits           requests that reached the vulnerable code (yield, rewards exploitation)
  interesting_total   interesting responses found (yield; counts duplicates of the same finding)
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from itertools import product
from pathlib import Path

import numpy as np

try:
    from scipy.stats import fisher_exact, mannwhitneyu
except ImportError:                      # scipy optional: p-values are skipped without it
    mannwhitneyu = fisher_exact = None

SUMMARY_METRICS = ["distinct_outcomes", "first_interesting", "sink_hits", "interesting_total"]
METRICS = ["outcome_auc"] + SUMMARY_METRICS
COMPARED = ["ml", "bandit", "llm"]


def a12(x, y):
    return float(np.mean([(xi > yi) + 0.5 * (xi == yi) for xi, yi in product(x, y)]))


def outcome_auc(records, budget):
    """Mean number of distinct server outcomes seen after each of the first `budget` requests."""
    seen, total, n = set(), 0, 0
    for r in sorted(records, key=lambda r: r.get("i", 0))[:budget]:
        if r.get("outcome") is not None:
            seen.add(r["outcome"])
        total += len(seen)
        n += 1
    if n == 0:
        return None
    return (total + len(seen) * (budget - n)) / budget      # a short run keeps its final count


def n_500(summary):
    sc = summary.get("status_counts", {})
    return sc.get(500, sc.get("500", 0))


def pvalue(m, b):
    if not mannwhitneyu:
        return None
    try:
        return float(mannwhitneyu(m, b, alternative="two-sided").pvalue)
    except ValueError:               # all values identical
        return 1.0


def verdict(p, a):
    """The pre-registered decision rule (SPRINT1.md section 8)."""
    if p is None:
        return "n/a (scipy missing)"
    if p < 0.05 and a >= 0.64:
        return "HELPS"
    if p < 0.05 and a <= 0.36:
        return "HURTS"
    return "no evidence"


def load(out_dir):
    cells = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    llm_usage = defaultdict(list)                       # target -> [usage dicts]
    rows = []                                           # one flat row per run (for --csv)
    for p in sorted(Path(out_dir).glob("run_*.json")):
        d = json.loads(p.read_text())
        m, s = d["meta"], d["summary"]
        auc = outcome_auc(d.get("records", []), m["budget"])
        rows.append(dict(target=m["target"], wordlist=m.get("wordlist", "-"), strategy=m["strategy"],
                         seed=m["seed"], budget=m["budget"], outcome_auc=None if auc is None else round(auc, 3),
                         **{k: s[k] for k in SUMMARY_METRICS}, bug_500s=n_500(s),
                         sink_rate=round(s["sink_hits"] / m["budget"], 4)))
        store = cells[(m["target"], m.get("wordlist", "-"))][m["strategy"]]
        for k in SUMMARY_METRICS:
            v = s[k]
            if k == "first_interesting" and v is None:
                v = m["budget"] + 1       # censored: never found within the budget
            store[k].append(v)
        if auc is not None:
            store["outcome_auc"].append(auc)
        store["bug_found"].append(int(n_500(s) > 0))
        if m["strategy"] == "llm":
            llm_usage[m["target"]].append(m.get("params", {}).get("usage", {}))
    # The LLM is wordlist-independent: compare it against every wordlist cell of its target.
    for (target, wl) in list(cells):
        if wl == "none":
            continue
        llm = cells.get((target, "none"), {}).get("llm")
        if llm:
            cells[(target, wl)]["llm"] = llm
    for key in [k for k in cells if k[1] == "none"]:
        del cells[key]
    return cells, llm_usage, rows


def row(cell, k, name, b, m):
    pv = pvalue(m, b)
    p = f"{pv:9.4f}" if pv is not None else "      n/a"
    print(f"{cell[0] + '/' + cell[1]:24}{name:8}{k:20}{np.median(b):9.1f} [{b.mean():7.2f}]"
          f"{np.median(m):9.1f} [{m.mean():7.2f}]{a12(m, b):7.2f}{p}  {len(b)}v{len(m)}")


def decision(cells):
    print("DECISION (pre-registered): primary metric outcome_auc; a variant HELPS only if p < 0.05 and A12 >= 0.64")
    print(f"{'cell':24}{'vs':8}{'A12':>6}{'p':>9}  {'verdict':13}{'runs with a 500 (planted bug): base vs strat':>46}  Fisher p")
    for cell, strategies in sorted(cells.items()):
        base = strategies.get("baseline")
        if not base:
            continue
        for name in COMPARED:
            st = strategies.get(name)
            if not st:
                continue
            bb, sb = base["bug_found"], st["bug_found"]
            fp = ""
            if fisher_exact and bb and sb:
                fp = f"{fisher_exact([[sum(sb), len(sb) - sum(sb)], [sum(bb), len(bb) - sum(bb)]])[1]:.4f}"
            bugs = f"{sum(bb)}/{len(bb)} vs {sum(sb)}/{len(sb)}"
            if base["outcome_auc"] and st["outcome_auc"]:
                b, m = np.array(base["outcome_auc"], float), np.array(st["outcome_auc"], float)
                pv, a = pvalue(m, b), a12(m, b)
                ps = f"{pv:9.4f}" if pv is not None else "      n/a"
                print(f"{cell[0] + '/' + cell[1]:24}{name:8}{a:6.2f}{ps}  {verdict(pv, a):13}{bugs:>46}  {fp}")
            else:
                print(f"{cell[0] + '/' + cell[1]:24}{name:8}{'':6}{'':9}  {'no records':13}{bugs:>46}  {fp}")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir", nargs="?", default="results/matrix")
    ap.add_argument("--csv", help="also write one row per run (small; safe to commit) to this path")
    a = ap.parse_args()
    cells, llm_usage, rows = load(a.out_dir)
    if not cells:
        sys.exit(f"No run_*.json found in {a.out_dir}")
    if a.csv:
        Path(a.csv).parent.mkdir(parents=True, exist_ok=True)
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} rows to {a.csv}\n")
    print(f"{'cell':24}{'vs':8}{'metric':20}{'base med [mean]':>19}{'strat med [mean]':>19}{'A12':>7}{'p':>9}  n")
    for cell, strategies in sorted(cells.items()):
        if "baseline" not in strategies:
            print(f"{cell[0] + '/' + cell[1]:24}(no baseline runs)")
            continue
        for name in COMPARED:
            if name not in strategies:
                continue
            for k in METRICS:
                if not strategies["baseline"][k] or not strategies[name][k]:
                    continue                      # e.g. outcome_auc when a run file has no records
                b = np.array(strategies["baseline"][k], float)
                m = np.array(strategies[name][k], float)
                row(cell, k, name, b, m)
        print()
    decision(cells)
    if llm_usage:
        print("LLM cost per run (mean over seeds):")
        for target, us in sorted(llm_usage.items()):
            g = lambda key: float(np.mean([u.get(key, 0) for u in us]))
            calls = max(g("calls"), 1e-9)
            print(f"  {target}: calls={g('calls'):.1f}  input_tokens={g('input_tokens'):.0f}  "
                  f"output_tokens={g('output_tokens'):.0f}  latency/call={g('latency_ms') / calls:.0f} ms  "
                  f"fallback_payloads={g('fallback_payloads'):.1f}  failed_calls={g('failed_calls'):.1f}  "
                  f"invalid={g('invalid_payloads'):.1f}  duplicate={g('duplicate_payloads'):.1f}  (n={len(us)})")
            if g("fallback_payloads") > 0:
                print("    WARNING: some payloads came from the baseline fallback (API failures); "
                      "those runs are not pure LLM runs.")


if __name__ == "__main__":
    main()
