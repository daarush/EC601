#!/usr/bin/env bash
# verify_dvwa.sh — Smoke test for the DVWA Docker target.
# Proves: image pulls, container starts, login page is reachable.
# Usage: bash scripts/verify_dvwa.sh

set -euo pipefail

IMAGE="vulnerables/web-dvwa"
CONTAINER_NAME="ec601-dvwa-smoke"
PORT=8080

cleanup() {
    echo "[*] Stopping container..."
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[1/4] Pulling $IMAGE..."
docker pull "$IMAGE"

echo "[2/4] Starting container on port $PORT..."
docker run -d --name "$CONTAINER_NAME" -p "$PORT:80" "$IMAGE"

echo "[3/4] Waiting for DVWA to become ready (up to 30s)..."
for i in {1..30}; do
    if curl -sf "http://127.0.0.1:$PORT/login.php" -o /dev/null; then
        echo "[OK] DVWA login page is reachable at http://127.0.0.1:$PORT/login.php"
        echo "[4/4] Smoke test PASSED."
        exit 0
    fi
    sleep 1
done

echo "[FAIL] DVWA did not respond within 30 seconds."
exit 1