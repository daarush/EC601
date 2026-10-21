"""make_figures.py - Sprint 1 figures from results/*.json.
Usage (repo root): uv run --with matplotlib python scripts/make_figures.py [results_dir] [out_dir]
Defaults: results_dir=results, out_dir=docs/figures
"""
import collections, glob, json, math, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/figures"); OUT.mkdir(parents=True, exist_ok=True)
EXCLUDE = {10}
C = {"unin": "#8da0cb", "in": "#fc8d62", "man": "#66c2a5"}
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})

def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z*z/n; c = (p + z*z/(2*n))/d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return max(0, c-h), min(1, c+h)

runs = []
for f in sorted(glob.glob(str(RES / "run_*.json"))):
    d = json.load(open(f, encoding="utf-8")); m = d["meta"]
    if m["seed"] in EXCLUDE: continue
    m["wl"] = m.get("wordlist") or ("informed" if m["budget"] == 1000 else "mini")
    runs.append((m, d["summary"], d["records"]))
def sel(t, wl): return [r for r in runs if r[0]["target"] == t and r[0]["wl"] == wl]
A_un, A_in, B_un, B_in = sel("flask_app","mini"), sel("flask_app","informed"), sel("vuln_site","mini"), sel("vuln_site","informed")
def recs(g): return [r for _, _, R in g for r in R]

# ---- Fig 1: Site A validation funnel -------------------------------------
STAGES = ["JSON valid","Fields present","Email format","Not blacklisted","Username length","Query OK + WAF","SEARCH: prefix","Sink reached"]
def reach(g):
    D = [r["depth"] for r in recs(g)]
    return [100*sum(d >= k for d in D)/len(D) for k in range(1, 9)]
fig, ax = plt.subplots(figsize=(9, 5))
y = range(len(STAGES)); h = 0.26
ax.barh([i+h for i in y], reach(A_un), h, color=C["unin"], label=f"Uninformed baseline (5 seeds x 200 = {len(recs(A_un))} req)")
ax.barh(list(y), reach(A_in), h, color=C["in"], label=f"Informed baseline (1 seed x {len(recs(A_in))} req)")
ax.barh([i-h for i in y], [100]*8, h, color=C["man"], label="10 manual payloads")
ax.set_yticks(list(y)); ax.set_yticklabels([f"{i+1}. {s}" for i, s in enumerate(STAGES)]); ax.invert_yaxis()
ax.set_xlabel("% of requests that passed this stage"); ax.set_xlim(0, 108)
ax.set_title("Site A: how far do requests get through the validation chain?", fontweight="bold")
for i, v in enumerate(reach(A_in)):
    if i >= 6: ax.text(v+1.2, i, f"{v:.1f}%", va="center", fontsize=9, color="#c0501f")
for i in (6, 7): ax.text(1.2, i+h, "0%", va="center", fontsize=9, color="#4a5a9a")
ax.legend(loc="lower left", frameon=False, fontsize=9, bbox_to_anchor=(0.0, -0.32), ncol=1)
fig.tight_layout(); fig.savefig(OUT/"fig1_site_a_funnel.png", dpi=170); plt.close(fig)

# ---- Fig 2: Site A vs Site B outcome rates ---------------------------------
def rate(g, fn):
    R = recs(g); k = sum(fn(r) for r in R); n = len(R); lo, hi = wilson(k, n); return 100*k/n, 100*lo, 100*hi, k, n
cfg = [("Site A\nuninformed", A_un, "unin"), ("Site A\ninformed", A_in, "in"), ("Site A\nmanual (10)", None, "man"),
       ("Site B\nuninformed", B_un, "unin"), ("Site B\ninformed", B_in, "in")]
fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
for ax, (title, fn) in zip(axes, [("Reached the sink / SQL layer", lambda r: r["sink_reached"]),
                                  ("Triggered a 500 (bug found)", lambda r: r["status"] == 500)]):
    for i, (lab, g, c) in enumerate(cfg):
        if g is None:
            v, lo, hi, k, n = (100.0, 72.3, 100.0, 10, 10) if "sink" in title else (50.0, 23.7, 76.3, 5, 10)
        else:
            v, lo, hi, k, n = rate(g, fn)
        ax.bar(i, v, color=C[c], yerr=[[v-lo], [hi-v]], capsize=3, ecolor="#444")
        ax.text(i, min(hi+3, 108), f"{k}/{n}", ha="center", fontsize=9)
    ax.set_xticks(range(5)); ax.set_xticklabels([c[0] for c in cfg], fontsize=8.5)
    ax.set_ylim(0, 115); ax.set_ylabel("% of requests"); ax.set_title(title, fontweight="bold")
fig.suptitle("Hard target (A) vs easy target (B): the same fuzzer, very different outcomes", fontweight="bold")
fig.text(0.5, 0.005, "Error bars: 95% Wilson CI. Informed runs are n=1 seed at budget 1000; manual runs are 10 requests.", ha="center", fontsize=8.5, color="#555")
fig.tight_layout(rect=(0, 0.03, 1, 0.95)); fig.savefig(OUT/"fig2_site_a_vs_b.png", dpi=170); plt.close(fig)

# ---- Fig 3: per-seed view -------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
ax = axes[0]; BUD = 200
for g, c, lab, xo in [(A_un, "#d95f02", "Site A", -0.12), (B_un, "#1b9e77", "Site B", 0.12)]:
    for m, s, R in g:
        fi = s["first_interesting"]; x = m["seed"]+xo
        if fi is None: ax.scatter(x, BUD+8, marker="x", s=70, color=c)
        else: ax.scatter(x, fi, s=60, color=c)
    ax.scatter([], [], color=c, label=lab)
ax.scatter([], [], marker="x", color="#d95f02", label="Site A: nothing found")
ax.axhline(BUD, ls="--", color="#999", lw=1); ax.text(46.45, BUD-9, "budget (200)", ha="right", fontsize=8, color="#777")
ax.set_xticks([42,43,44,45,46]); ax.set_xlabel("seed"); ax.set_ylabel("request # of first interesting response")
ax.set_ylim(0, 225); ax.set_title("Requests to first interesting response", fontweight="bold"); ax.legend(frameon=False, fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3)
ax = axes[1]; seeds = [42,43,44,45,46]
q, nb = [], []
for s in seeds:
    R = [r for m, _, RR in B_un if m["seed"] == s for r in RR if r["status"] == 500]
    q.append(sum("OperationalError" in r["body"] for r in R)); nb.append(sum("ProgrammingError" in r["body"] for r in R))
ax.bar(seeds, q, color="#1b9e77", label="quote -> SQL syntax error")
ax.bar(seeds, nb, bottom=q, color="#a6d854", label="null byte -> ProgrammingError")
ax.bar(seeds, [0]*5, color="#d95f02", label="Site A: 0 in every seed")
ax.set_xticks(seeds); ax.set_xlabel("seed"); ax.set_ylabel("500 responses (of 200)"); ax.set_ylim(0, 5)
ax.set_title("Site B bugs per seed (uninformed, 200 req)", fontweight="bold"); ax.legend(frameon=False, fontsize=8.5, loc="upper right")
fig.tight_layout(); fig.savefig(OUT/"fig3_per_seed.png", dpi=170); plt.close(fig)
print("wrote", sorted(p.name for p in OUT.glob("*.png")))
