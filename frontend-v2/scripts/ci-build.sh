#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
pnpm install --frozen-lockfile --ignore-scripts
pnpm exec tsc --noEmit --project tsconfig.json
pnpm run build
test -f dist/index.html
