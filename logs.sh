#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ -f backend/logs.log ]; then
  tail -n 200 -f backend/logs.log
else
  echo "No backend/logs.log found yet. Start the app first with ./run.sh"
fi
