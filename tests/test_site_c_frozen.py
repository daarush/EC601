"""Guards the pre-registration: once Site C is frozen, its code, wordlists and registry entry must not change.
If this fails because you changed Site C ON PURPOSE, run `uv run python scripts/freeze_check.py --update` and
discard every Site C result collected before the change."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "freeze_check", Path(__file__).resolve().parent.parent / "scripts" / "freeze_check.py")
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


def test_site_c_is_frozen_and_unchanged():
    assert fc.check() == []


def test_digest_ignores_line_endings(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "ROOT", tmp_path)
    (tmp_path / "a.txt").write_bytes(b"x\r\ny\r\n")
    lf = fc.file_digest("a.txt")
    (tmp_path / "a.txt").write_bytes(b"x\ny\n")
    assert fc.file_digest("a.txt") == lf
