"""freeze_check.py - verify that Site C and its wordlists are exactly as they were when frozen.

Pre-registration rule (docs/SITE_C.md): Site C is calibrated against the BASELINE only, then frozen BEFORE any
ML / bandit / LLM variant is run on it. This script records and checks SHA-256 hashes (line endings normalised, so
Windows/Linux checkouts agree) of everything that defines the experiment.

    uv run python scripts/freeze_check.py            # check; exit code 1 on mismatch
    uv run python scripts/freeze_check.py --update   # DELIBERATE re-freeze (invalidates all Site C results)
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FREEZE_FILE = ROOT / "docs" / "site_c.freeze.json"
FILES = ["targets/shop_site/app.py", "data/wordlists/mini.txt", "data/wordlists/shop_docs.txt"]


def file_digest(rel: str) -> str:
    data = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def target_digest() -> str:
    sys.path.insert(0, str(ROOT))
    from fuzzer.targets import TARGETS
    return hashlib.sha256(json.dumps(TARGETS["shop"], sort_keys=True).encode()).hexdigest()


def current() -> dict:
    return {"files": {f: file_digest(f) for f in FILES}, "target_entry": target_digest()}


def check() -> list[str]:
    """Return a list of human-readable differences (empty list = frozen state intact)."""
    frozen = json.loads(FREEZE_FILE.read_text())
    now = current()
    problems = [f"{f} changed since the freeze" for f in FILES if now["files"][f] != frozen["files"].get(f)]
    if now["target_entry"] != frozen["target_entry"]:
        problems.append("TARGETS['shop'] (URL / seed request) changed since the freeze")
    return problems


def main():
    if "--update" in sys.argv:
        old = json.loads(FREEZE_FILE.read_text()) if FREEZE_FILE.exists() else {}
        old.update(current())
        FREEZE_FILE.write_text(json.dumps(old, indent=2) + "\n")
        print(f"re-frozen: {FREEZE_FILE}  (all earlier Site C results are now INVALID)")
        return
    problems = check()
    if problems:
        print("FREEZE VIOLATED:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("Site C is frozen and unchanged.")


if __name__ == "__main__":
    main()
