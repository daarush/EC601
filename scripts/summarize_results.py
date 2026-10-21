"""summarize_results.py - regenerate the Sprint 1 results tables from results/*.json.

Usage (from repo root):
    uv run python scripts/summarize_results.py results

Reads only the raw per-request records, so every number is recomputable.
Wordlist is not stored in run meta (yet), so budget==1000 is treated as the
informed.txt control (see SPRINT1.md, Section 8, fix (b)).
"""
import collections
import glob
import json
import math
import sys
from pathlib import Path

RESULTS = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
EXCLUDE_SEEDS = {10}          # stray dev run, not part of the experiment matrix


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100*k/n:.1f}%, CI {100*lo:.1f}-{100*hi:.1f})"


def load():
    runs = []
    for f in sorted(glob.glob(str(RESULTS / "run_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        m = d["meta"]
        if m["seed"] in EXCLUDE_SEEDS:
            continue
        m["wordlist"] = m.get("wordlist") or ("informed (inferred)" if m["budget"] == 1000 else "mini")
        runs.append((m, d["summary"], d["records"]))
    return runs


def err_class(r):
    b = r.get("body", "")
    if r["status"] != 500:
        return None
    if "ProgrammingError" in b:
        return "null-byte (ProgrammingError)"
    if "OperationalError" in b:
        return "quote/syntax (OperationalError)"
    return "other 5xx"


def main():
    runs = load()
    groups = collections.defaultdict(list)
    for m, s, R in runs:
        groups[(m["target"], m["wordlist"], m["budget"])].append((m, s, R))

    print("## Per-run results\n")
    print("| Target | Wordlist | Budget | Seed | 1st interesting | Interesting | 500s | Sink hits (rate) | Max depth |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (t, w, b), g in sorted(groups.items()):
        for m, s, R in g:
            n500 = sum(r["status"] == 500 for r in R)
            print(f"| {t} | {w} | {b} | {m['seed']} | {s['first_interesting']} | {s['interesting_total']} | "
                  f"{n500} | {pct(s['sink_hits'], len(R))} | {s['max_depth']} |")

    print("\n## Pooled by configuration\n")
    print("| Target | Wordlist | Budget | Runs | Sink-reach rate | 500 rate | Runs with >=1 interesting | Median 1st interesting (None = censored) |")
    print("|---|---|---|---|---|---|---|---|")
    for (t, w, b), g in sorted(groups.items()):
        N = sum(len(R) for _, _, R in g)
        sink = sum(s["sink_hits"] for _, s, _ in g)
        n500 = sum(sum(r["status"] == 500 for r in R) for _, _, R in g)
        hit = sum(s["first_interesting"] is not None for _, s, _ in g)
        firsts = sorted(s["first_interesting"] for _, s, _ in g if s["first_interesting"] is not None)
        med = firsts[len(firsts) // 2] if firsts else None
        print(f"| {t} | {w} | {b} | {len(g)} | {pct(sink, N)} | {pct(n500, N)} | {hit}/{len(g)} | {med} |")

    print("\n## Site A: how far do requests get? (pooled, P(depth >= k))\n")
    STAGES = ["json_ok", "presence_ok", "email_ok", "blacklist_ok", "length_ok", "query_ok", "prefix_ok", "sink_reached"]
    for (t, w, b), g in sorted(groups.items()):
        if t != "flask_app":
            continue
        N = sum(len(R) for _, _, R in g)
        depths = [r["depth"] for _, _, R in g for r in R]
        print(f"**{w}, budget {b}, {len(g)} run(s), {N} requests**\n")
        print("| Stage passed | Requests reaching it |")
        print("|---|---|")
        for k, name in enumerate(STAGES, 1):
            print(f"| {k}. {name} | {pct(sum(d >= k for d in depths), N)} |")
        print()

    print("## Site B: what the 500s actually are\n")
    print("| Wordlist | Budget | Quote/syntax errors | Null-byte errors | Total 500 | Distinct error classes |")
    print("|---|---|---|---|---|---|")
    for (t, w, b), g in sorted(groups.items()):
        if t != "vuln_site":
            continue
        c = collections.Counter(err_class(r) for _, _, R in g for r in R if r["status"] == 500)
        print(f"| {w} | {b} | {c['quote/syntax (OperationalError)']} | {c['null-byte (ProgrammingError)']} | "
              f"{sum(c.values())} | {len(c)} |")

    print("\n## Site A informed run: how the 12 sink hits were produced\n")
    for (t, w, b), g in sorted(groups.items()):
        if t == "flask_app" and b == 1000:
            hits = [r for _, _, R in g for r in R if r["sink_reached"]]
            c = collections.Counter(r["payload"].get("query") for r in hits)
            print("| `query` sent | Count |")
            print("|---|---|")
            for q, n in c.most_common():
                print(f"| `{q}` | {n} |")
            print(f"\nTotal sink hits: {len(hits)}")


if __name__ == "__main__":
    main()
