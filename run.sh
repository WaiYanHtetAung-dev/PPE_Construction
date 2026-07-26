#!/usr/bin/env bash
# Starts the PPE Detect platform in the background on a fixed port and
# hands the terminal back immediately. Use ./logs.sh to watch logs and
# ./stop.sh to stop it.
set -e
cd "$(dirname "$0")"

PORT="${PPE_PORT:-8000}"
PID_FILE=".ppe_platform.pid"
LOG_FILE="backend/logs.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Already running (PID $(cat "$PID_FILE")) at http://localhost:$PORT"
  exit 0
fi

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r backend/requirements.txt >/dev/null

mkdir -p backend
: > "$LOG_FILE"   # start each run with a clean log file

cd backend
nohup uvicorn main:app --host 0.0.0.0 --port "$PORT" >> logs.log 2>&1 &
PID=$!
cd ..
echo $PID > "$PID_FILE"

# Give it a moment, then confirm it actually stayed up.
sleep 2
if ! kill -0 "$PID" 2>/dev/null; then
  echo "Failed to start — check backend/logs.log (or run ./errors.sh)."
  rm -f "$PID_FILE"
  exit 1
fi

LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo "PPE Detect Platform is running (PID $PID)"
echo "  On this machine: http://localhost:$PORT"
if [ -n "$LAN_IP" ]; then
  echo "  On your LAN:     http://$LAN_IP:$PORT"
fi
echo "  Logs:  ./logs.sh"
echo "  Stop:  ./stop.sh"
echo ""
