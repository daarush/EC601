import json, random, time
from collections import Counter
from pathlib import Path
import httpx
from .mutators import mutate_request

SIGNATURES = ["Traceback", "sqlite3.", "SQL syntax", "Exception"]

class BaselineStrategy:
    name = "baseline"
    def __init__(self, seed_request, words, seed):
        self.seed_request, self.words = seed_request, words
        self.rng = random.Random(seed)
        self.first = True
    def next_payload(self):
        if self.first:
            self.first = False
            return dict(self.seed_request)   # calibration request
        return mutate_request(self.seed_request, self.rng, self.words)
    def observe(self, record): pass          # baseline ignores feedback

def _send(client, t, payload):
    if t["kind"] == "json":  return client.post(t["url"], json=payload)
    if t["kind"] == "form":  return client.post(t["url"], data=payload)
    return client.get(t["url"], params=payload)

def client_interesting(rec) -> bool:
    return (rec["status"] or 0) >= 500 or any(s in rec.get("body", "") for s in SIGNATURES)

def run(target, strategy, budget, client=None):
    client = client or httpx.Client(timeout=5.0)
    if target.get("reset_url"): client.post(target["reset_url"])
    records = []
    for i in range(budget):                      # exactly `budget` requests
        payload = strategy.next_payload()
        t0 = time.perf_counter()
        try:
            r = _send(client, target, payload)
            rec = {"status": r.status_code, "body": r.text[:300],
                   "body_len": len(r.content), "cid": r.headers.get("X-Correlation-ID")}
        except httpx.HTTPError as e:
            rec = {"status": None, "body": "", "body_len": 0, "cid": None, "error": repr(e)}
        rec.update(i=i, payload=payload, latency_ms=(time.perf_counter() - t0) * 1000)
        rec["client_interesting"] = client_interesting(rec)
        strategy.observe(rec); records.append(rec)
    _join_server_log(client, target, records)
    return records

def _join_server_log(client, target, records):
    """Attach ground truth by correlation ID; apply oracle (a)+(b)+(c)."""
    server = {}
    if target.get("logs_url"):
        server = {e["correlation_id"]: e for e in client.get(target["logs_url"]).json()["entries"]}
    best = None
    for rec in records:
        s = server.get(rec["cid"], {})
        rec["depth"], rec["sink_reached"] = s.get("depth", 0), s.get("sink_reached", False)
        rec["new_depth"] = best is not None and rec["depth"] > best
        best = rec["depth"] if best is None else max(best, rec["depth"])
        rec["interesting"] = rec["client_interesting"] or rec["new_depth"]

def summarize(records):
    hits = [r["i"] for r in records if r["interesting"]]
    return {"requests": len(records), "first_interesting": hits[0] if hits else None,
            "interesting_total": len(hits), "max_depth": max((r["depth"] for r in records), default=0),
            "sink_hits": sum(r["sink_reached"] for r in records),
            "status_counts": dict(Counter(r["status"] for r in records))}

def save(records, target_name, strat_name, seed, budget) -> Path:
    Path("results").mkdir(exist_ok=True)
    p = Path(f"results/run_{target_name}_{strat_name}_s{seed}_b{budget}.json")
    p.write_text(json.dumps({"meta": dict(target=target_name, strategy=strat_name, seed=seed,
                 budget=budget), "summary": summarize(records), "records": records}, indent=1))
    return p