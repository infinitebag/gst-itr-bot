📄 README.md

# GST / ITR WhatsApp Bot

A FastAPI-based WhatsApp bot for GST & ITR workflows with background jobs, Redis queues, and PostgreSQL.

**Tech stack**
- FastAPI + Uvicorn
- PostgreSQL (Docker)
- Redis (Docker)
- RQ workers
- Docker + Docker Compose
- Makefile for one-command workflows

> 🚫 Local Python / venv is NOT required.  
> ✅ Everything runs inside Docker.

---

## 1. Prerequisites

Install **once**:

### macOS
- Docker Desktop: https://www.docker.com/products/docker-desktop
- Make (already installed on most Macs)

### Windows
- Docker Desktop (WSL2 enabled)
- Git Bash or WSL Ubuntu (recommended)

Verify:
```bash
docker --version
docker compose version
make --version


⸻

2. Repository Structure

.
├── app/
│   ├── main.py
│   ├── config/
│   ├── infrastructure/
│   └── domain/
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── .env.docker
├── README.md
└── CONTRIBUTING.md


⸻

3. Environment Configuration (IMPORTANT)

Use Docker env only

Create .env.docker in project root:

ENV=dev
PORT=8000

DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/gst_itr_db
REDIS_URL=redis://redis:6379/0

# WhatsApp
WHATSAPP_VERIFY_TOKEN=change_me
WHATSAPP_ACCESS_TOKEN=change_me
WHATSAPP_PHONE_NUMBER_ID=change_me

ADMIN_API_KEY=change_this
SESSION_IDLE_MINUTES=10

⚠️ DO NOT
	•	use localhost for DB or Redis
	•	use .env.local for Docker runs

Docker networking uses service names (db, redis).

⸻

4. First-Time Setup (One Command)

make up

This will:
	•	build app + worker images
	•	start PostgreSQL
	•	start Redis
	•	start FastAPI app
	•	start background worker

Access:
	•	API → http://localhost:8000
	•	Health → http://localhost:8000/health (if implemented)

⸻

5. Daily Development Workflow (Incremental)

🔁 After code changes

make build
make restart

🔁 OR simply

make up

(Docker will reuse cache automatically)

⸻

6. Useful Commands

Action	Command
Start everything	make up
Start only DB + Redis	make up-deps
Start app + worker	make up-app
Incremental build	make build
Clean rebuild	make rebuild
Restart app	make restart
Stop containers	make down
Delete DB data	make clean
Show containers	make ps
Follow all logs	make logs
App logs	make app-logs
Worker logs	make worker-logs
Shell into app	make sh
Shell into worker	make worker-sh
Postgres shell	make psql
Redis shell	make redis-cli


⸻

7. Database Notes

Where is Postgres data stored?
	•	In a Docker volume
	•	Survives container restarts
	•	Deleted only by:

make clean

Running migrations / ALTER scripts

make psql

Example:

ALTER TABLE invoices ADD COLUMN gstin TEXT;


⸻

8. Common Errors & Fixes

❌ no such service: postgres

✅ Fix:
	•	Service name is db
	•	Use make psql, not docker compose exec postgres

⸻

❌ role "postgres" does not exist

✅ Fix:
	•	DB container not initialized

make clean
make up


⸻

❌ Redis connection error (redis:6379)

✅ Fix:
	•	Ensure Redis is running:

make ps
make up-deps


⸻

❌ Ellipsis object has no attribute __module__

✅ Cause:
	•	default_queue.enqueue(...) with ...

✅ Fix:
	•	Always pass a real function:

default_queue.enqueue(send_whatsapp_message, payload)


⸻

9. Architecture (High-Level)

Client (WhatsApp)
      ↓
FastAPI App
      ↓
RQ Queue (Redis)
      ↓
Worker
      ↓
PostgreSQL


⸻

10. Production Notes
	•	Use managed Postgres (Neon / RDS)
	•	Use managed Redis
	•	Keep Docker image same
	•	Change env vars only

⸻

11. Support

If Docker behaves weirdly:

docker system prune -af
make clean
make up


⸻

🚀 Happy shipping!

---

App:
👉 http://localhost:8000
Health:
👉 http://localhost:8000/health