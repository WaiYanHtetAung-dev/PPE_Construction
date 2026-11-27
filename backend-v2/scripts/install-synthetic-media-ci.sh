#!/bin/sh
set -eu

# Run on a disposable Ubuntu x86-64 GitHub-hosted runner.
archive="${RUNNER_TEMP:?}/mediamtx.tar.gz"
sudo apt-get update
sudo apt-get install -y --no-install-recommends ffmpeg
curl --fail --location --silent --show-error --retry 3 -o "$archive" \
    https://github.com/bluenviron/mediamtx/releases/download/v1.21.3/mediamtx_v1.21.3_linux_amd64.tar.gz
printf '%s  %s\n' '0a2ea7eba96023631efa1bea7804823a9145b043b6646a8a05798d4ac24ed635' "$archive" | sha256sum -c
tar -xzf "$archive" -C "$RUNNER_TEMP" mediamtx
test -x "$RUNNER_TEMP/mediamtx"
