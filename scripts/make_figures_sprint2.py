"""make_figures_sprint2.py - Sprint 2 figures: base fuzzer vs ML scorer vs bandit on Sites A, B and C.

Usage (repo root):
    uv run --with matplotlib --with pandas python scripts/make_figures_sprint2.py
    uv run --with matplotlib --with pandas python scripts/make_figures_sprint2.py --csv results/summary.csv --matrix results/matrix --out docs/figures
(matplotlib and pandas are not project dependencies, so they are added per run with --with; nothing is installed permanently)

Inputs
    results/summary.csv  one row per run (written by `scripts/compare_strategies.py --csv`); used for figures 5-7
    results/matrix/      the raw run files; used only for figure 8 (discovery curves), skipped if absent

Figures (Sprint 1 made fig1-fig4 with scripts/make_figures.py)
    fig5_sprint2_reach_vs_coverage.png   left: % of requests that reached the vulnerable code; right: the pre-registered
                                         primary metric. The whole story at a glance: big differences left, none right.
    fig6_sprint2_per_seed_auc.png        the primary metric for every single run, per cell (the overlap is the result)
    fig7_sprint2_bugs_triggered.png      share of runs that triggered each planted bug ("caught X vs Y")
    fig8_sprint2_discovery_curves.png    distinct outcomes found as the request budget is spent
"""
import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from scipy.stats import mannwhitneyu
except ImportError:
    mannwhitneyu = None

CELLS = [("flask_app", "mini"), ("flask_app", "mini_token"), ("flask_app", "informed"),
         ("vuln_site", "mini"), ("shop", "mini"), ("shop", "shop_docs")]
SITE = {"flask_app": "A", "vuln_site": "B", "shop": "C"}
STRATS = ["baseline", "ml", "bandit"]
NAME = {"baseline": "Base fuzzer (Sprint 1)", "ml": "ML scorer (Sprint 2)", "bandit": "Bandit (Sprint 2)"}
COL = {"baseline": "#8da0cb", "ml": "#fc8d62", "bandit": "#66c2a5"}
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})


def cell_label(cell, newline=True):
    return f"Site {SITE[cell[0]]}{chr(10) if newline else ' / '}{cell[1]}"


def mean_ci(x):
    x = np.asarray(x, float)
    return x.mean(), (1.96 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else 0.0)


def a12(x, y):
    x, y = np.asarray(x), np.asarray(y)
    return float(((x[:, None] > y[None, :]).sum() + 0.5 * (x[:, None] == y[None, :]).sum()) / (len(x) * len(y)))


def rule_summary(df):
    """Pre-registered rule on outcome_auc: 'helps' iff Mann-Whitney p < 0.05 and A12 >= 0.64. Returns (helps, total)."""
    if mannwhitneyu is None:
        return None
    helps = total = 0
    for cell in CELLS:
        g = df[(df.target == cell[0]) & (df.wordlist == cell[1])]
        base = g[g.strategy == "baseline"].outcome_auc.values
        for s in ("ml", "bandit"):
            x = g[g.strategy == s].outcome_auc.values
            if len(base) and len(x):
                total += 1
                p = mannwhitneyu(x, base, alternative="two-sided").pvalue if np.ptp(np.r_[x, base]) > 0 else 1.0
                helps += bool(p < 0.05 and a12(x, base) >= 0.64)
    return helps, total


def seeds_note(df):
    n = df.groupby(["target", "wordlist", "strategy"]).size()
    return f"{n.min()}" if n.min() == n.max() else f"{n.min()}-{n.max()}"


def fig5(df, out):
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.0))
    w = 0.26
    panels = [("sink_rate", 100, "Requests that reached the vulnerable code", "% of requests (higher = more hits)"),
              ("outcome_auc", 1, "Primary metric: outcome-coverage AUC", "outcome AUC (higher = better)")]
    for ax, (col, scale, title, ylabel) in zip(axes, panels):
        for j, s in enumerate(STRATS):
            ms, cis = [], []
            for cell in CELLS:
                g = df[(df.target == cell[0]) & (df.wordlist == cell[1]) & (df.strategy == s)][col] * scale
                m, ci = mean_ci(g)
                ms.append(m); cis.append(ci)
            ax.bar(np.arange(len(CELLS)) + (j - 1) * w, ms, w, yerr=cis, capsize=2.5, color=COL[s], ecolor="#444", label=NAME[s])
        ax.set_xticks(range(len(CELLS)))
        ax.set_xticklabels([cell_label(c) for c in CELLS], fontsize=8.5)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(title, fontweight="bold")
    axes[0].legend(frameon=False, fontsize=8.5, loc="upper left")
    rs = rule_summary(df)
    verdict = "" if rs is None else f"  Pre-registered rule (p<0.05 and A12>=0.64): {rs[0]} of {rs[1]} comparisons show a benefit."
    fig.suptitle("Learned fuzzers can hit vulnerable code more often, but none finds more kinds of behaviour", fontweight="bold")
    fig.text(0.5, 0.005, f"{seeds_note(df)} seeds x 1,000 requests per bar. Error bars: 95% CI of the mean.{verdict}",
             ha="center", fontsize=8.5, color="#555")
    fig.tight_layout(rect=(0, 0.035, 1, 0.95))
    fig.savefig(out / "fig5_sprint2_reach_vs_coverage.png", dpi=170)
    plt.close(fig)


def fig6(df, out):
    rng = np.random.default_rng(0)
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7.0))
    for ax, cell in zip(axes.ravel(), CELLS):
        g = df[(df.target == cell[0]) & (df.wordlist == cell[1])]
        data = [g[g.strategy == s].outcome_auc.values for s in STRATS]
        bp = ax.boxplot(data, widths=0.55, patch_artist=True, showfliers=False, medianprops=dict(color="#222"))
        for patch, s in zip(bp["boxes"], STRATS):
            patch.set(facecolor=COL[s], alpha=0.45)
        for i, (vals, s) in enumerate(zip(data, STRATS), start=1):
            ax.scatter(i + rng.uniform(-0.17, 0.17, len(vals)), vals, s=11, color=COL[s], edgecolor="#333", linewidth=0.3, zorder=3)
        ax.set_xticks([1, 2, 3]); ax.set_xticklabels(["base", "ML", "bandit"], fontsize=9)
        ax.set_title(cell_label(cell, newline=False), fontsize=10, fontweight="bold")
    for ax in axes[:, 0]:
        ax.set_ylabel("outcome AUC")
    fig.suptitle("Primary metric for every run: the three fuzzers overlap almost completely", fontweight="bold")
    fig.text(0.5, 0.005, f"One dot = one run ({seeds_note(df)} seeds per box). Higher = more distinct outcomes found, earlier. Each panel has its own zoomed y-axis.",
             ha="center", fontsize=8.5, color="#555")
    fig.tight_layout(rect=(0, 0.025, 1, 0.95))
    fig.savefig(out / "fig6_sprint2_per_seed_auc.png", dpi=170)
    plt.close(fig)


def bug_counts(df):
    """(label, {strategy: (runs that triggered it, runs)}) for every planted bug we have ground truth for."""
    def count(mask, fn):
        res = {}
        for s in STRATS:
            g = df[mask & (df.strategy == s)]
            res[s] = (int(fn(g).sum()), len(g))
        return res
    bugs = df.bugs_found.fillna("") if "bugs_found" in df else pd.Series("", index=df.index)
    rows = [("Site A\nhidden server error\n(HTTP 500, 3 wordlists)", count(df.target == "flask_app", lambda g: g.bug_500s > 0)),
            ("Site B\nSQL injection\n(HTTP 500)", count(df.target == "vuln_site", lambda g: g.bug_500s > 0))]
    for bug, label in [("sqli_error", "Site C\nSQL injection"), ("coupon_parser_crash", "Site C\ncoupon crash\n(needs token SAVE)"),
                       ("express_zero_division", "Site C\nexpress divide-by-zero\n(needs express + qty 10)"),
                       ("premium_crash", "Site C TRIPWIRE\n(must stay 0)")]:
        rows.append((label, count(df.target == "shop", lambda g, b=bug: bugs.loc[g.index].str.contains(b))))
    return rows


def fig7(df, out):
    rows = bug_counts(df)
    fig, ax = plt.subplots(figsize=(13.5, 5.2))
    w = 0.26
    for j, s in enumerate(STRATS):
        shares = [100 * r[1][s][0] / r[1][s][1] for r in rows]
        ax.bar(np.arange(len(rows)) + (j - 1) * w, shares, w, color=COL[s], label=NAME[s])
        for i, r in enumerate(rows):
            k, n = r[1][s]
            ax.text(i + (j - 1) * w, shares[i] + 1.5, f"{k}/{n}", ha="center", fontsize=8)
    ax.set_xticks(range(len(rows))); ax.set_xticklabels([r[0] for r in rows], fontsize=8.5)
    ax.set_ylim(0, 114); ax.set_yticks(range(0, 101, 20)); ax.set_ylabel("% of runs that triggered the bug")
    ax.set_title("Which planted bugs did each fuzzer trigger?", fontweight="bold")
    ax.legend(frameon=False, fontsize=9, loc="upper right", bbox_to_anchor=(1.0, 1.0))
    fig.text(0.5, 0.005, "Labels = runs that triggered the bug / runs. Same bug repeated many times within a run counts once. "
             "Site A: p = 0.052 for ML vs base (borderline). Tripwire must be 0 for a valid target.",
             ha="center", fontsize=8.5, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out / "fig7_sprint2_bugs_triggered.png", dpi=170)
    plt.close(fig)


def fig8(matrix, out):
    files = glob.glob(str(Path(matrix) / "run_*.json"))
    if not files:
        print(f"skipping fig8: no run files in {matrix}")
        return False
    curves = {}
    for f in files:
        d = json.load(open(f, encoding="utf-8"))
        m = d["meta"]
        if m["strategy"] not in STRATS or not m.get("wordlist"):
            continue
        seen, curve = set(), []
        for r in sorted(d["records"], key=lambda r: r["i"]):
            if r.get("outcome"):
                seen.add(r["outcome"])
            curve.append(len(seen))
        curve += [len(seen)] * (m["budget"] - len(curve))
        curves.setdefault(((m["target"], m["wordlist"]), m["strategy"]), []).append(curve)
    present = [c for c in CELLS if any((c, s) in curves for s in STRATS)]
    if not present:
        print("skipping fig8: no usable runs")
        return False
    ncol = min(3, len(present))
    nrow = int(np.ceil(len(present) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(12.5, 3.6 * nrow), squeeze=False)
    for ax, cell in zip(axes.ravel(), present):
        for s in STRATS:
            if (cell, s) not in curves:
                continue
            arr = np.array(curves[(cell, s)], float)
            mean = arr.mean(axis=0)
            se = arr.std(axis=0, ddof=1) / np.sqrt(len(arr)) if len(arr) > 1 else np.zeros_like(mean)
            x = np.arange(1, len(mean) + 1)
            ax.plot(x, mean, color=COL[s], label=NAME[s], lw=1.8)
            ax.fill_between(x, mean - 1.96 * se, mean + 1.96 * se, color=COL[s], alpha=0.18, linewidth=0)
        ax.set_xscale("log"); ax.set_xlabel("requests sent (log scale)")
        ax.set_title(cell_label(cell, newline=False), fontsize=10, fontweight="bold")
    for ax in axes[:, 0]:
        ax.set_ylabel("distinct outcomes found")
    for ax in axes.ravel()[len(present):]:
        ax.axis("off")
    axes[0, 0].legend(frameon=False, fontsize=8)
    fig.suptitle("Discovery curves: outcomes found as the budget is spent", fontweight="bold")
    fig.text(0.5, 0.005, "Mean over seeds; band = 95% CI of the mean.", ha="center", fontsize=8.5, color="#555")
    fig.tight_layout(rect=(0, 0.025, 1, 0.95))
    fig.savefig(out / "fig8_sprint2_discovery_curves.png", dpi=170)
    plt.close(fig)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default="results/summary.csv")
    ap.add_argument("--matrix", default="results/matrix")
    ap.add_argument("--out", default="docs/figures")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if not Path(a.csv).exists():
        sys.exit(f"{a.csv} not found. Run: uv run python scripts/compare_strategies.py --csv {a.csv}")
    df = pd.read_csv(a.csv)
    missing = [c for c in ("outcome_auc", "sink_rate", "bug_500s", "strategy", "target", "wordlist") if c not in df]
    if missing:
        sys.exit(f"{a.csv} is missing columns {missing}; regenerate it with the current compare_strategies.py --csv")
    df = df[df.strategy.isin(STRATS)]
    fig5(df, out); fig6(df, out); fig7(df, out)
    made8 = fig8(a.matrix, out)
    print("wrote", sorted(p.name for p in out.glob("fig[5-8]_*.png")), "" if made8 else "(fig8 skipped)")


if __name__ == "__main__":
    main()
