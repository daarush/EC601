import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")        # not project dependencies: run with `uv run --with matplotlib --with pandas pytest`
pytest.importorskip("pandas")
import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "mf2", Path(__file__).resolve().parent.parent / "scripts" / "make_figures_sprint2.py")
mf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mf)


def _df(effect=0.0, n=12, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for target, wl in mf.CELLS:
        for s in mf.STRATS:
            for i in range(n):
                shop = target == "shop"
                bug = ["sqli_error"] if shop and i % 2 == 0 else []
                rows.append(dict(target=target, wordlist=wl, strategy=s, seed=i, budget=1000,
                                 outcome_auc=5 + rng.normal(0, .3) + (effect if s == "ml" else 0),
                                 distinct_outcomes=6, first_interesting=None, sink_hits=10, interesting_total=1,
                                 bug_500s=int(i % 3 == 0), sink_rate=0.01, bugs_found=";".join(bug)))
    return pd.DataFrame(rows)


def test_rule_summary_counts_a_real_benefit_and_ignores_noise():
    pytest.importorskip("scipy")
    assert mf.rule_summary(_df(effect=0.0))[0] == 0
    helps, total = mf.rule_summary(_df(effect=3.0))           # ML clearly better in all 6 cells
    assert helps == 6 and total == 12


def test_a12():
    assert mf.a12([2, 3], [0, 1]) == 1.0 and mf.a12([1], [1]) == 0.5


def test_bug_counts_match_the_data():
    rows = dict((label.split("\n")[0] + "|" + label.split("\n")[1], v) for label, v in mf.bug_counts(_df()))
    site_c_sql = rows["Site C|SQL injection"]
    assert site_c_sql["baseline"] == (12, 24)                  # i even in 12 runs x 2 shop cells
    assert rows["Site C TRIPWIRE|(must stay 0)"]["ml"] == (0, 24)


def test_figures_5_to_7_are_written(tmp_path):
    df = _df()
    mf.fig5(df, tmp_path); mf.fig6(df, tmp_path); mf.fig7(df, tmp_path)
    names = sorted(p.name for p in tmp_path.glob("*.png"))
    assert names == ["fig5_sprint2_reach_vs_coverage.png", "fig6_sprint2_per_seed_auc.png", "fig7_sprint2_bugs_triggered.png"]
    assert all((tmp_path / n).stat().st_size > 5000 for n in names)


def test_fig8_needs_run_files_and_draws_curves_from_them(tmp_path):
    assert mf.fig8(tmp_path / "nothing", tmp_path) is False
    mdir = tmp_path / "matrix"; mdir.mkdir()
    for s in mf.STRATS:
        for seed in (1, 2):
            recs = [{"i": i, "outcome": "a" if i < 3 else "b"} for i in range(20)]
            meta = dict(target="shop", strategy=s, wordlist="mini", seed=seed, budget=20)
            (mdir / f"run_shop_{s}_mini_s{seed}_b20.json").write_text(json.dumps({"meta": meta, "records": recs}))
    assert mf.fig8(mdir, tmp_path) is True
    assert (tmp_path / "fig8_sprint2_discovery_curves.png").exists()


def test_main_explains_a_missing_csv(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["x", "--csv", str(tmp_path / "nope.csv"), "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        mf.main()
    assert "not found" in str(e.value)
