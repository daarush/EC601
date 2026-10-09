TARGETS = {
    "flask_app": dict(
        url="http://127.0.0.1:5000/submit", kind="json",
        logs_url="http://127.0.0.1:5000/logs", reset_url="http://127.0.0.1:5000/reset",
        seed_request={"username": "alice@example.com", "query": "hello world"}),
    "vuln_site": dict(
        url="http://127.0.0.1:5001/search", kind="query",
        logs_url="http://127.0.0.1:5001/logs", reset_url="http://127.0.0.1:5001/reset",
        seed_request={"q": "widget", "limit": "10"}),
}