#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
if [[ -d "$project_dir/.tools/node-v22.16.0-linux-x64/bin" ]]; then
  export PATH="$project_dir/.tools/node-v22.16.0-linux-x64/bin:$PATH"
fi
if [[ -d "$project_dir/.tools/browser-libs/usr/lib/x86_64-linux-gnu" ]]; then
  export LD_LIBRARY_PATH="$project_dir/.tools/browser-libs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
fi
if [[ ! -x .venv/bin/python ]]; then
  echo '请先按 README 安装 Python 依赖并初始化数据。' >&2
  exit 1
fi
if [[ ! -f frontend/dist/index.html ]]; then
  npm run build --prefix frontend
fi
.venv/bin/python -m backend.worker &
export_pid=$!
cleanup() { kill "$export_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port "${ERP_PORT:-8000}"
