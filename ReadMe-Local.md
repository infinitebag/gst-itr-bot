5.1. Start Redis (if you have Docker)
        docker run --name gst-redis -p 6379:6379 -d redis:7-alpine
   Or if you installed Redis via brew:
        brew install redis
        redis-server

5.2. Run FastAPI app
From project root (with .venv activated):
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

5.3. Run Arq worker in another terminal
    arq worker app.infrastructure.queue.arq_settings.WorkerSettings