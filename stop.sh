#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PID_FILE=".ppe_platform.pid"

if [ -f "$PID_FILE" ]; then
  pid=$(cat "$PID_FILE")
  if kill -0 "$pid" 2>/dev/null; then
    echo "Stopping PPE Detect Platform (PID $pid)..."
    kill "$pid"
    rm -f "$PID_FILE"
    echo "Stopped."
    exit 0
  else
    echo "PID file found but process $pid isn't running — cleaning up."
    rm -f "$PID_FILE"
  fi
fi

# Fallback: find uvicorn by command line in case the pid file is missing.
if command -v pgrep >/dev/null 2>&1; then
  pid=$(pgrep -f "uvicorn main:app" || true)
  if [ -n "$pid" ]; then
    echo "Stopping uvicorn (PID $pid)"
    kill $pid
    exit 0
  fi
fi

echo "No running PPE Detect Platform process found."
