"""
cheapest_test.py — Send 10 hand-crafted payloads to Site A.
Proves a human (or LLM) CAN reach the sink when the baseline cannot.
Run with Site A up: uv run python targets/flask_app/app.py
"""
import httpx

URL = "http://127.0.0.1:5000/submit"

PAYLOADS = [
    # 5 clean sink-reaching (expect 200)
    {"username": "user01@example.com", "query": "SEARCH: normal query one"},
    {"username": "user02@example.com", "query": "SEARCH: normal query two"},
    {"username": "user03@example.com", "query": "SEARCH: normal query three"},
    {"username": "user04@example.com", "query": "SEARCH: normal query four"},
    {"username": "user05@example.com", "query": "SEARCH: normal query five"},
    # 5 planted-bug triggers (expect 500)
    {"username": "user06@example.com", "query": "SEARCH: query with ' quote"},
    {"username": "user07@example.com", "query": "SEARCH: it's a test query"},
    {"username": "user08@example.com", "query": "SEARCH: quote' injection"},
    {"username": "user09@example.com", "query": "SEARCH: another ' here"},
    {"username": "user10@example.com", "query": "SEARCH: final ' payload"},
]


def main():
    print("Sending 10 hand-crafted payloads to Site A...")
    print(f"{'#':<4} {'Status':<8} {'CID':<40}")
    print("-" * 52)

    statuses = []
    for i, p in enumerate(PAYLOADS):
        try:
            r = httpx.post(URL, json=p, timeout=5.0)
            cid = r.headers.get("X-Correlation-ID", "MISSING")
            statuses.append(r.status_code)
            print(f"{i+1:<4} {r.status_code:<8} {cid}")
        except httpx.ConnectError:
            print(f"[FAIL] Cannot connect to {URL}. Is Site A running?")
            return

    s200 = statuses.count(200)
    s500 = statuses.count(500)
    s_other = len(statuses) - s200 - s500

    print("\n" + "=" * 52)
    print(f"RESULTS:")
    print(f"  200 (clean sink hit):    {s200}/10")
    print(f"  500 (planted bug hit):   {s500}/10")
    print(f"  Other (validation fail): {s_other}/10")
    print(f"  Sink-reach rate:         {(s200 + s500) * 10}%")
    print(f"\n  Baseline was: 0/200 = 0% sink-reach in 200 requests.")
    print(f"  Manual is:    {s200 + s500}/10 = {(s200+s500)*10}% in 10 requests.")
    print("=" * 52)


if __name__ == "__main__":
    main()