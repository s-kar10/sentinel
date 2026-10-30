#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
node -e 'if (process.versions.node.split(".")[0] !== "22") { throw new Error("Sentinel checks require Node.js 22"); }'
npm run lint
# build includes TypeScript checking.
npm run build
