from pathlib import Path


def test_mini_token_is_mini_plus_exactly_the_token():
    mini = [w for w in Path("data/wordlists/mini.txt").read_text(encoding="utf-8").splitlines() if w]
    tok = [w for w in Path("data/wordlists/mini_token.txt").read_text(encoding="utf-8").splitlines() if w]
    assert tok[: len(mini)] == mini
    assert tok[len(mini):] == ["SEARCH:"]


def test_matrix_wordlists_exist():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_matrix", "scripts/run_matrix.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for wls in m.MATRIX.values():
        for wl in wls:
            assert (m.WORDLISTS / f"{wl}.txt").exists(), wl
