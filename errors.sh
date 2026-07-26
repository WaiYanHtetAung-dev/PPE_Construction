#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ -f backend/logs.log ]; then
  tail -n 200 -f backend/logs.log | grep -i --line-buffered 'error' || true
else
  echo "No backend/logs.log found."
fi
