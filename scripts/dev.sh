#!/usr/bin/env bash
set -e

# Start Redis (docker) if not running
if ! docker ps --format '{{.Names}}' | grep -q '^gst-redis$'; then
  echo "Starting Redis container..."
  docker run --name gst-redis -p 6379:6379 -d redis:7-alpine
fi

echo "Starting FastAPI (uvicorn)..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
API_PID=$!

echo "Starting Arq worker..."
arq worker app.infrastructure.queue.arq_settings.WorkerSettings &
WORKER_PID=$!

trap "kill $API_PID $WORKER_PID" INT

wait