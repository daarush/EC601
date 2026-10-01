"""
verify_llm_api.py — One-shot smoke test for the OpenAI API.

Proves:
  1. .env is loaded correctly
  2. API key is valid
  3. A real request round-trips
  4. Latency is logged (needed for your cost/latency metrics later)

Usage:
    uv run python scripts/verify_llm_api.py

Requires OPENAI_API_KEY in .env (see .env.example).
"""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def main() -> None:
    # Load .env from repo root (one level up from scripts/).
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        raise SystemExit(
            f"[FAIL] .env not found at {env_path}. "
            "Copy .env.example -> .env and fill in OPENAI_API_KEY."
        )
    load_dotenv(env_path)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key.startswith("sk-your"):
        raise SystemExit("[FAIL] OPENAI_API_KEY is missing or still a placeholder.")

    client = OpenAI(api_key=api_key)

    print("[1/3] Sending test prompt to OpenAI API...")
    t0 = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # cheap model for the smoke test
            messages=[{"role": "user", "content": "Reply with exactly: PONG"}],
            max_tokens=10,
        )
    except Exception as e:
        raise SystemExit(f"[FAIL] API call failed: {e}")
    latency_ms = (time.perf_counter() - t0) * 1000

    content = response.choices[0].message.content.strip()
    usage = response.usage

    print(f"[2/3] Response: {content!r}")
    print(f"[3/3] Latency: {latency_ms:.0f} ms")
    if usage:
        print(f"       Tokens — prompt: {usage.prompt_tokens}, "
              f"completion: {usage.completion_tokens}, "
              f"total: {usage.total_tokens}")

    if "PONG" in content.upper():
        print("[OK] LLM API smoke test PASSED.")
    else:
        print("[WARN] API responded but did not return expected 'PONG'. "
              "Check your model name / key.")


if __name__ == "__main__":
    main()