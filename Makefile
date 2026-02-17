SHELL := /bin/bash

# ─── Environment ──────────────────────────────────────────────────────
# Use .env.docker for Docker networking (db/redis hostnames = service names)
ENV_FILE ?= .env.docker
DC := docker compose --env-file $(ENV_FILE)

.PHONY: help \
	setup up up-prod up-deps up-app build rebuild restart down clean \
	ps logs app-logs worker-logs db-logs redis-logs \
	sh worker-sh psql redis-cli run \
	db-init db-revision db-upgrade db-downgrade db-history db-current db-reset \
	lint fmt check compile-check \
	test test-cov \
	health health-json \
	tunnel \
	env-check seed-ca first-run

.DEFAULT_GOAL := help

# ─── Help ─────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║            GST + ITR WhatsApp Bot — Makefile              ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo " 🚀 Quick Start"
	@echo "   make first-run       Full first-time setup (build → migrate → start)"
	@echo "   make setup           Copy .env.example → .env.docker (if missing)"
	@echo ""
	@echo " 🐳 Docker Lifecycle"
	@echo "   make up              Build + start all services (dev mode)"
	@echo "   make up-prod         Build + start for PRODUCTION (no --reload, base deps only)"
	@echo "   make up-deps         Start only db + redis"
	@echo "   make up-app          Start app + worker (expects deps already up)"
	@echo "   make build           Incremental build (uses Docker cache)"
	@echo "   make rebuild         Full rebuild (no Docker cache)"
	@echo "   make restart         Restart app + worker containers"
	@echo "   make down            Stop all containers"
	@echo "   make clean           Stop + remove volumes (⚠️  DELETES DB DATA)"
	@echo ""
	@echo " 📊 Status & Logs"
	@echo "   make ps              Show container statuses"
	@echo "   make logs            Follow ALL container logs"
	@echo "   make app-logs        Follow app container logs"
	@echo "   make worker-logs     Follow worker container logs"
	@echo "   make db-logs         Follow PostgreSQL logs"
	@echo "   make redis-logs      Follow Redis logs"
	@echo ""
	@echo " 🔌 Shell Access"
	@echo "   make sh              Shell into app container"
	@echo "   make worker-sh       Shell into worker container"
	@echo "   make psql            Open psql prompt in db container"
	@echo "   make redis-cli       Open redis-cli in redis container"
	@echo "   make run CMD='...'   Run ad-hoc command in app container"
	@echo ""
	@echo " 🗄️  Database (Alembic)"
	@echo "   make db-init         Create initial migration + apply"
	@echo "   make db-revision MSG='...'  Generate new migration"
	@echo "   make db-upgrade      Apply all pending migrations"
	@echo "   make db-downgrade REV='...' Rollback to a revision"
	@echo "   make db-history      Show migration history"
	@echo "   make db-current      Show current migration revision"
	@echo "   make db-reset        ⚠️  Drop all tables and re-migrate"
	@echo ""
	@echo " 🩺 Health Check"
	@echo "   make health          Open system health dashboard (browser)"
	@echo "   make health-json     Fetch health status as JSON"
	@echo ""
	@echo " ✅ Code Quality"
	@echo "   make lint            Run ruff linter"
	@echo "   make fmt             Auto-format code with ruff"
	@echo "   make check           Lint + format check (no changes)"
	@echo "   make compile-check   Verify all Python files compile"
	@echo "   make test            Run pytest"
	@echo "   make test-cov        Run pytest with coverage report"
	@echo ""
	@echo " 🔧 Utilities"
	@echo "   make tunnel          Open ngrok tunnel to localhost:8000"
	@echo "   make env-check       Validate required env vars are set"
	@echo "   make seed-ca         Create a default CA user for testing"
	@echo ""

# ─── Quick Start ──────────────────────────────────────────────────────
setup:
	@if [ ! -f .env.docker ]; then \
		cp .env.example .env.docker; \
		echo "✅ Created .env.docker from .env.example"; \
		echo "👉 Edit .env.docker and fill in your API keys before running 'make up'"; \
	else \
		echo "ℹ️  .env.docker already exists — skipping"; \
	fi

first-run: setup
	@echo ""
	@echo "═══════════════════════════════════════════"
	@echo " Step 1/3: Building containers..."
	@echo "═══════════════════════════════════════════"
	$(DC) up -d --build
	@echo ""
	@echo "═══════════════════════════════════════════"
	@echo " Step 2/3: Waiting for services to be healthy..."
	@echo "═══════════════════════════════════════════"
	@sleep 5
	@echo ""
	@echo "═══════════════════════════════════════════"
	@echo " Step 3/3: Running database migrations..."
	@echo "═══════════════════════════════════════════"
	$(DC) exec app alembic upgrade head
	@echo ""
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║  ✅ First-run complete!                                    ║"
	@echo "║                                                            ║"
	@echo "║  App:     http://localhost:8000                            ║"
	@echo "║  API Docs:http://localhost:8000/api/docs    (Swagger UI)  ║"
	@echo "║  ReDoc:   http://localhost:8000/api/redoc                  ║"
	@echo "║  Health:  http://localhost:8000/admin/system-health        ║"
	@echo "║  Admin:   http://localhost:8000/admin/ui/usage             ║"
	@echo "║  CA:      http://localhost:8000/ca/auth/login              ║"
	@echo "║                                                            ║"
	@echo "║  Next steps:                                               ║"
	@echo "║  1. Edit .env.docker with your WhatsApp/OpenAI keys       ║"
	@echo "║  2. make restart                                           ║"
	@echo "║  3. make tunnel   (to expose webhook to Meta)             ║"
	@echo "╚════════════════════════════════════════════════════════════╝"

# ─── Docker Lifecycle ─────────────────────────────────────────────────
up:
	$(DC) up -d --build

up-prod:
	DOCKER_TARGET=production $(DC) up -d --build

up-deps:
	$(DC) up -d db redis

up-app:
	$(DC) up -d --build app worker

build:
	$(DC) build app worker

rebuild:
	$(DC) build --no-cache app worker

restart:
	$(DC) restart app worker

down:
	$(DC) down

clean:
	@echo "⚠️  This will DELETE all database data and Redis data!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	$(DC) down -v --remove-orphans

# ─── Status & Logs ────────────────────────────────────────────────────
ps:
	$(DC) ps

logs:
	$(DC) logs -f --tail=200

app-logs:
	$(DC) logs -f --tail=200 app

worker-logs:
	$(DC) logs -f --tail=200 worker

db-logs:
	$(DC) logs -f --tail=200 db

redis-logs:
	$(DC) logs -f --tail=200 redis

# ─── Shell Access ─────────────────────────────────────────────────────
sh:
	$(DC) exec app sh

worker-sh:
	$(DC) exec worker sh

psql:
	$(DC) exec db psql -U postgres -d gst_itr_db

redis-cli:
	$(DC) exec redis redis-cli

run:
	$(DC) exec app sh -lc '$(CMD)'

# ─── Database / Alembic ───────────────────────────────────────────────
db-init:
	$(DC) exec app alembic revision --autogenerate -m "initial"
	$(DC) exec app alembic upgrade head
	@echo "✅ Initial migration created and applied"

db-revision:
	@if [ -z "$(MSG)" ]; then echo "❌ Usage: make db-revision MSG='describe your change'"; exit 1; fi
	$(DC) exec app alembic revision --autogenerate -m "$(MSG)"

db-upgrade:
	$(DC) exec app alembic upgrade head

db-downgrade:
	@if [ -z "$(REV)" ]; then echo "❌ Usage: make db-downgrade REV='-1' or REV='<revision_hash>'"; exit 1; fi
	$(DC) exec app alembic downgrade $(REV)

db-history:
	$(DC) exec app alembic history --verbose

db-current:
	$(DC) exec app alembic current

db-reset:
	@echo "⚠️  This will DROP all tables and re-run all migrations!"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 1
	$(DC) exec app alembic downgrade base
	$(DC) exec app alembic upgrade head
	@echo "✅ Database reset complete"

# ─── Health Check ─────────────────────────────────────────────────────
health:
	@echo "Opening health dashboard..."
	@open http://localhost:8000/admin/system-health 2>/dev/null || \
		xdg-open http://localhost:8000/admin/system-health 2>/dev/null || \
		echo "Visit: http://localhost:8000/admin/system-health"

health-json:
	@token=$$(grep "^ADMIN_API_KEY=" $(ENV_FILE) 2>/dev/null | cut -d'=' -f2-); \
	curl -s -H "X-Admin-Token: $${token:-dev_admin_key}" http://localhost:8000/admin/system-health/json | python3 -m json.tool

# ─── Code Quality ─────────────────────────────────────────────────────
lint:
	$(DC) exec app ruff check app/

fmt:
	$(DC) exec app ruff format app/

check:
	$(DC) exec app ruff check app/ --no-fix
	$(DC) exec app ruff format app/ --check

compile-check:
	@echo "Compiling all Python files..."
	@find app/ -name "*.py" -exec python3 -m py_compile {} + && echo "✅ All files compile OK" || echo "❌ Compilation errors found"

test:
	$(DC) exec app python -m pytest -q tests/

test-cov:
	$(DC) exec app python -m pytest --cov=app --cov-report=term-missing tests/

# ─── Utilities ────────────────────────────────────────────────────────
tunnel:
	@echo "Starting Cloudflare Tunnel (api.mytaxpe.com → localhost:8000) ..."
	@echo "Webhook URL: https://api.mytaxpe.com/webhook"
	cloudflared tunnel run gst-itr-bot

tunnel-ngrok:
	@echo "Starting ngrok tunnel to localhost:8000 (local dev fallback) ..."
	@echo "After starting, set your webhook URL in Meta Developer Console"
	ngrok http 8000

env-check:
	@echo "Checking required environment variables in $(ENV_FILE)..."
	@missing=0; \
	for var in DATABASE_URL REDIS_URL WHATSAPP_VERIFY_TOKEN WHATSAPP_ACCESS_TOKEN \
	           WHATSAPP_PHONE_NUMBER_ID WHATSAPP_APP_SECRET OPENAI_API_KEY CA_JWT_SECRET USER_JWT_SECRET ADMIN_JWT_SECRET; do \
		val=$$(grep "^$$var=" $(ENV_FILE) 2>/dev/null | cut -d'=' -f2-); \
		if [ -z "$$val" ] || [ "$$val" = "change-me-in-production" ] || [ "$$val" = "change_this_in_real_env" ] || [ "$$val" = "dev_admin_key" ] || [ "$$val" = "change-me-user-jwt" ] || [ "$$val" = "change-me-admin-jwt" ]; then \
			echo "  ❌ $$var — not set or using default"; \
			missing=$$((missing+1)); \
		else \
			echo "  ✅ $$var"; \
		fi; \
	done; \
	echo ""; \
	if [ $$missing -gt 0 ]; then \
		echo "⚠️  $$missing variable(s) need attention in $(ENV_FILE)"; \
	else \
		echo "✅ All required variables are set!"; \
	fi

seed-ca:
	@echo "Creating default CA user (admin@example.com / admin123)..."
	$(DC) exec app python -c "\
import asyncio; \
from app.core.db import AsyncSessionLocal; \
from app.infrastructure.db.models import CAUser; \
from passlib.context import CryptContext; \
pwd = CryptContext(schemes=['bcrypt']); \
async def seed(): \
    async with AsyncSessionLocal() as s: \
        existing = (await s.execute(__import__('sqlalchemy').select(CAUser).where(CAUser.email=='admin@example.com'))).scalar_one_or_none(); \
        if existing: print('ℹ️  CA user already exists'); return; \
        s.add(CAUser(email='admin@example.com', password_hash=pwd.hash('admin123'), full_name='Admin CA', icai_membership_number='TEST001')); \
        await s.commit(); print('✅ CA user created: admin@example.com / admin123'); \
asyncio.run(seed())"
