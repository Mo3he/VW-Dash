#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Backend ───────────────────────────────────────────────────────────────────
echo "▶ Starting backend..."
cd "$ROOT/backend"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

mkdir -p "$ROOT/data"

# Apply patch to carconnectivity VW auth (hybrid OIDC flow fix for broken BFF endpoint)
PATCH_TARGET=$(.venv/bin/python3 -c "import carconnectivity_connectors.volkswagen.auth.we_connect_session as m; import inspect; print(inspect.getfile(m))" 2>/dev/null || true)
if [ -n "$PATCH_TARGET" ]; then
  patch --forward --silent "$PATCH_TARGET" "$ROOT/backend/patches/we_connect_session.patch" || true
fi

.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
echo "  Backend PID: $BACKEND_PID"

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "▶ Starting frontend..."
cd "$ROOT/frontend"

if [ ! -d "node_modules" ]; then
  npm install --silent
fi

npm run dev &
FRONTEND_PID=$!
echo "  Frontend PID: $FRONTEND_PID"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "✓ VW Dash running"
echo "  Dashboard → http://localhost:3000"
echo "  API       → http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop both services."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT INT TERM
wait
