"""make_figures.py - Sprint 1 figures from the clean baseline matrix (results/matrix/*.json).

Usage (repo root):
    uv run --with matplotlib python scripts/make_figures.py [matrix_dir] [out_dir]
Defaults: matrix_dir=results/matrix, out_dir=docs/figures

The "manual payloads" bars come from scripts/cheapest_test.py (10 requests: 10 reached the sink,
5 triggered the planted bug); they are constants here because that script does not write a results file.
"""
import collections, glob, json, math, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES = Path(sys.argv[1] if len(sys.argv) > 1 else "results/matrix")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/figures"); OUT.mkdir(parents=True, exist_ok=True)
BUDGET = 1000
MANUAL = {"sink": (10, 10), "bug": (5, 10)}
COL = {"mini": "#8da0cb", "mini_token": "#e5c494", "informed": "#fc8d62", "manual": "#66c2a5"}
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z*z/n; c = (p + z*z/(2*n))/d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return max(0, c-h), min(1, c+h)

runs = collections.defaultdict(list)          # (target, wordlist) -> [(seed, summary, records)]
for f in sorted(glob.glob(str(RES / "run_*.json"))):
    d = json.load(open(f, encoding="utf-8")); m = d["meta"]
    if m["budget"] != BUDGET or not m.get("wordlist"): continue
    runs[(m["target"], m["wordlist"])].append((m["seed"], d["summary"], d["records"]))
if not runs: sys.exit(f"No budget-{BUDGET} runs with a wordlist found in {RES}. Run scripts/run_matrix.py first.")
A = {w: runs[("flask_app", w)] for w in ("mini", "mini_token", "informed")}
B = runs[("vuln_site", "mini")]
SEEDS = sorted(s for s, _, _ in B)
def recs(g): return [r for _, _, R in g for r in R]
def nseeds(g): return len(g)

# ---- Fig 1: Site A validation funnel --------------------------------------
STAGES = ["JSON valid","Fields present","Email format","Not blacklisted","Username length","Query OK + WAF","SEARCH: prefix","Sink reached"]
def reach(g):
    D = [r["depth"] for r in recs(g)]
    return [100*sum(d >= k for d in D)/len(D) for k in range(1, 9)]
fig, ax = plt.subplots(figsize=(9.5, 5.6)); h = 0.2
series = [("mini", reach(A["mini"]), f"mini: no token ({nseeds(A['mini'])} seeds x {BUDGET})"),
          ("mini_token", reach(A["mini_token"]), f"mini + SEARCH: token only ({nseeds(A['mini_token'])} seeds x {BUDGET})"),
          ("informed", reach(A["informed"]), f"informed list, includes SEARCH:hello ({nseeds(A['informed'])} seeds x {BUDGET})"),
          ("manual", [100]*8, "10 manual payloads")]
for j, (k, vals, lab) in enumerate(series):
    ax.barh([i + (j-1.5)*h for i in range(8)], vals, h, color=COL[k], label=lab)
for i in (6, 7):
    for j, (k, vals, _) in enumerate(series[:3]):
        ax.text(vals[i]+1.2, i + (j-1.5)*h, f"{vals[i]:.2f}%" if vals[i] < 10 else f"{vals[i]:.0f}%", va="center", fontsize=8)
ax.set_yticks(range(8)); ax.set_yticklabels([f"{i+1}. {s}" for i, s in enumerate(STAGES)]); ax.invert_yaxis()
ax.set_xlabel("% of requests that passed this stage"); ax.set_xlim(0, 108)
ax.set_title("Site A: how far do requests get through the validation chain?", fontweight="bold")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), frameon=False, fontsize=8.5, ncol=1)
fig.tight_layout(); fig.savefig(OUT/"fig1_site_a_funnel.png", dpi=170); plt.close(fig)

# ---- Fig 2: Site A vs Site B outcome rates --------------------------------
def rate(g, fn):
    R = recs(g); k = sum(fn(r) for r in R); n = len(R); lo, hi = wilson(k, n); return 100*k/n, 100*lo, 100*hi, k, n
cfg = [("Site A\nmini", A["mini"], "mini"), ("Site A\ntoken only", A["mini_token"], "mini_token"),
       ("Site A\ninformed", A["informed"], "informed"), ("Site A\nmanual (10)", None, "manual"), ("Site B\nmini", B, "mini")]
fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
for ax, (title, fn, key) in zip(axes, [("Reached the sink / SQL layer", lambda r: r["sink_reached"], "sink"),
                                       ("Triggered a 500 (bug found)", lambda r: r["status"] == 500, "bug")]):
    for i, (lab, g, c) in enumerate(cfg):
        if g is None:
            k, n = MANUAL[key]; v = 100*k/n; lo, hi = [100*x for x in wilson(k, n)]
        else:
            v, lo, hi, k, n = rate(g, fn)
        ax.bar(i, v, color=COL[c], yerr=[[v-lo], [hi-v]], capsize=3, ecolor="#444")
        ax.text(i, min(hi+3, 109), f"{k}/{n}", ha="center", fontsize=8.5)
    ax.set_xticks(range(5)); ax.set_xticklabels([c[0] for c in cfg], fontsize=8.5)
    ax.set_ylim(0, 116); ax.set_ylabel("% of requests"); ax.set_title(title, fontweight="bold")
fig.suptitle("Hard target (A) vs easy target (B): the same baseline fuzzer, very different outcomes", fontweight="bold")
fig.text(0.5, 0.005, f"5 seeds x {BUDGET} requests per baseline bar; manual = 10 requests. Error bars: 95% Wilson CI.", ha="center", fontsize=8.5, color="#555")
fig.tight_layout(rect=(0, 0.03, 1, 0.95)); fig.savefig(OUT/"fig2_site_a_vs_b.png", dpi=170); plt.close(fig)

# ---- Fig 3: per-seed view -------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
ax = axes[0]
sets = [("Site A: mini", A["mini"], COL["mini"], -0.24), ("Site A: token only", A["mini_token"], COL["mini_token"], -0.08),
        ("Site A: informed", A["informed"], COL["informed"], 0.08), ("Site B: mini", B, "#1b9e77", 0.24)]
for lab, g, c, xo in sets:
    ax.scatter([], [], color=c, label=lab)
    for seed, s, _ in g:
        fi = s["first_interesting"]
        if fi is None: ax.scatter(seed+xo, BUDGET+45, marker="x", s=55, color=c)
        else: ax.scatter(seed+xo, fi, s=55, color=c)
ax.scatter([], [], marker="x", color="#555", label="x = nothing found")
ax.axhline(BUDGET, ls="--", color="#999", lw=1)
ax.set_xticks(SEEDS); ax.set_xlabel("seed"); ax.set_ylabel("request # of first interesting response")
ax.set_ylim(0, BUDGET*1.12); ax.set_title(f"Requests to first interesting response (budget {BUDGET})", fontweight="bold")
ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3)
ax = axes[1]
q, nb = [], []
for seed in SEEDS:
    R = [r for s, _, RR in B if s == seed for r in RR if r["status"] == 500]
    q.append(sum("OperationalError" in r["body"] for r in R)); nb.append(sum("ProgrammingError" in r["body"] for r in R))
ax.bar(SEEDS, q, color="#1b9e77", label="quote -> SQL syntax error")
ax.bar(SEEDS, nb, bottom=q, color="#a6d854", label="null byte -> ProgrammingError")
ax.set_xticks(SEEDS); ax.set_xlabel("seed"); ax.set_ylabel(f"500 responses (of {BUDGET})")
ax.set_title("Site B bugs per seed (Site A: 0 in every run)", fontweight="bold"); ax.legend(frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2)
fig.tight_layout(); fig.savefig(OUT/"fig3_per_seed.png", dpi=170); plt.close(fig)

# ---- Fig 4: outcome coverage (primary metric) and its ceiling -------------
def distinct(R):
    return len({r["outcome"] for r in R if r.get("outcome")})
if any(r.get("outcome") for _, _, R in B for r in R):
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    groups = [("Site A\nmini", A["mini"], "mini"), ("Site A\ntoken only", A["mini_token"], "mini_token"),
              ("Site A\ninformed", A["informed"], "informed"), ("Site B\nmini", B, "mini")]
    for i, (lab, g, c) in enumerate(groups):
        vals = [distinct(R) for _, _, R in sorted(g, key=lambda x: x[0])]
        ax.bar(i, sum(vals)/len(vals), color=COL[c], alpha=0.55)
        for j, v in enumerate(vals):
            ax.scatter(i + (j-2)*0.06, v, color="#222", s=14, zorder=3)
    ax.set_xticks(range(4)); ax.set_xticklabels([g[0] for g in groups])
    ax.set_ylabel("distinct server-side outcomes reached"); ax.set_ylim(0, 9)
    ax.set_title("Outcome coverage after 1,000 requests: little headroom for AI on these targets", fontweight="bold", fontsize=10)
    fig.text(0.5, 0.005, "Bars: mean over 5 seeds; dots: each seed. Site B reaches all 4 of its outcomes in every seed.", ha="center", fontsize=8.5, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1)); fig.savefig(OUT/"fig4_outcome_coverage.png", dpi=170); plt.close(fig)
print("wrote", sorted(p.name for p in OUT.glob("*.png")))
