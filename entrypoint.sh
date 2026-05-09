#!/bin/sh
set -e

cd /app/backend
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

node /app/frontend/proxy-server.js &
FRONTEND_PID=$!

echo "VW-Dash running on :3000"

wait $BACKEND_PID $FRONTEND_PID
