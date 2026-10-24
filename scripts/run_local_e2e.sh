#!/usr/bin/env bash
# Local three-agent end-to-end test (macOS / Linux).
# Starts Research (8001), Analyst (8002) and Orchestrator (8000), sends one
# real proposal from the test client (8003), checks the report, and stops
# every agent it started. Run from the repository root:
#   ./scripts/run_local_e2e.sh "https://snapshot.org/#/<space>/proposal/<id>"
# (or set DAO_PROPOSAL_URL in .env and run without an argument).
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
LOG_DIR="logs/e2e-$(date +%Y%m%d-%H%M%S)"
PIDS=()

fail() { echo "E2E: $*" >&2; exit 1; }

[ -x "$PY" ] || fail "No virtualenv Python at $PY. Create .venv and install requirements.txt first."
[ -f .env ] || fail "No .env. Run: $PY scripts/new_local_env.py"
"$PY" -c "import uagents, requests, bs4, dotenv" 2>/dev/null \
  || fail "Dependencies missing. Run: $PY -m pip install -r requirements.txt"

# Check required settings without printing any values.
"$PY" - <<'EOF' || exit 1
import os, sys
from dotenv import load_dotenv
# Explicit path: this snippet is fed on stdin, so there is no script frame for
# find_dotenv() to walk and it would assert. The repo root is the cwd here.
load_dotenv(".env")
keys = ["ORCHESTRATOR_SEED", "RESEARCH_AGENT_SEED", "ANALYSIS_AGENT_SEED", "TEST_CLIENT_SEED"]
values = [os.getenv(k, "").strip() for k in keys]
missing = [k for k, v in zip(keys, values) if not v]
if missing:
    sys.exit("E2E: missing in .env: " + ", ".join(missing))
if len(set(values)) != len(values):
    sys.exit("E2E: every agent needs a distinct seed.")
if os.getenv("DAOTHINK_LOCAL", "1").strip().lower() in {"0", "false", "no"}:
    sys.exit("E2E: set DAOTHINK_LOCAL=1 for the local test.")
EOF

if [ "${1:-}" != "" ]; then export DAO_PROPOSAL_URL="$1"; fi

for port in 8000 8001 8002 8003; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "Port $port is in use (stale agent?). Find it with: lsof -nP -iTCP:$port -sTCP:LISTEN"
  fi
done

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

mkdir -p "$LOG_DIR"
start() {  # name module port
  DAOTHINK_LOCAL=1 "$PY" -m "$2" >"$LOG_DIR/$1.log" 2>&1 &
  PIDS+=("$!")
  for _ in $(seq 1 40); do
    if lsof -nP -iTCP:"$3" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "E2E: $1 listening on $3"
      return 0
    fi
    sleep 0.5
  done
  echo "--- $1 log ---"; tail -n 40 "$LOG_DIR/$1.log" || true
  fail "$1 did not start on port $3."
}

start research research_agent.research_agent 8001
start analyst analyst.agent 8002
start orchestrator orchestrator.agent 8000

echo "E2E: sending proposal..."
set +e
DAOTHINK_LOCAL=1 "$PY" -m tests.send_local_request 2>&1 | tee "$LOG_DIR/client.log"
status=${PIPESTATUS[0]}
set -e

echo
if [ "$status" -eq 0 ]; then
  echo "E2E PASSED. Logs: $LOG_DIR"
else
  echo "E2E FAILED (exit $status). Logs: $LOG_DIR"
fi
exit "$status"
