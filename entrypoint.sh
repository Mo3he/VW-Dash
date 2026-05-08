#!/bin/sh
set -e

cd /app/backend
uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

PORT=3000 HOSTNAME=0.0.0.0 node /app/frontend/server.js &
FRONTEND_PID=$!

echo "VW-Dash running — dashboard :3000  API :8000"

wait $BACKEND_PID $FRONTEND_PID
