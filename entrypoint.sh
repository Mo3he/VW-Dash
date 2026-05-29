#!/bin/sh
set -e

# Apply patch to carconnectivity VW auth (hybrid OIDC flow fix for broken BFF endpoint)
PATCH_TARGET=$(python3 -c "import carconnectivity_connectors.volkswagen.auth.we_connect_session as m; import inspect; print(inspect.getfile(m))" 2>/dev/null || true)
if [ -n "$PATCH_TARGET" ]; then
  patch --forward --silent "$PATCH_TARGET" /app/backend/patches/we_connect_session.patch || true
fi

cd /app/backend
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

node /app/frontend/proxy-server.js &
FRONTEND_PID=$!

echo "VW-Dash running on :3000"

wait $BACKEND_PID $FRONTEND_PID
