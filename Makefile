SHELL := /bin/bash

# Use .env.docker for Docker networking (db/redis hostnames are service names)
ENV_FILE ?= .env.docker
DC := docker compose --env-file $(ENV_FILE)

.PHONY: help up up-deps up-app build rebuild restart down clean ps logs app-logs worker-logs sh worker-sh db psql redis-cli run

help:
	@echo ""
	@echo "Docker-only commands (ENV_FILE=$(ENV_FILE))"
	@echo ""
	@echo "  make up         - start everything (db/redis/app/worker) with build"
	@echo "  make up-deps    - start only db + redis"
	@echo "  make up-app     - start app + worker (expects deps already up)"
	@echo "  make build      - incremental build (uses Docker cache)"
	@echo "  make rebuild    - clean rebuild (no-cache)"
	@echo "  make restart    - restart app + worker"
	@echo "  make down       - stop containers"
	@echo "  make clean      - stop + remove volumes (DELETES DB DATA)"
	@echo "  make ps         - show containers"
	@echo "  make logs       - follow all logs"
	@echo "  make app-logs   - follow app logs"
	@echo "  make worker-logs- follow worker logs"
	@echo "  make sh         - shell into app container"
	@echo "  make worker-sh  - shell into worker container"
	@echo "  make psql       - open psql inside db container"
	@echo "  make redis-cli  - open redis-cli inside redis container"
	@echo ""

up:
	$(DC) up -d --build

up-deps:
	$(DC) up -d redis db

up-app:
	$(DC) up -d --build app worker

# Incremental build (fast; uses cache)
build:
	$(DC) build app worker

# Rebuild from scratch (slow; ignores cache)
rebuild:
	$(DC) build --no-cache app worker

restart:
	$(DC) restart app worker

down:
	$(DC) down

# WARNING: this deletes DB volume data
clean:
	$(DC) down -v --remove-orphans

ps:
	$(DC) ps

logs:
	$(DC) logs -f --tail=200

app-logs:
	$(DC) logs -f --tail=200 app

worker-logs:
	$(DC) logs -f --tail=200 worker

sh:
	$(DC) exec app sh

worker-sh:
	$(DC) exec worker sh

worker:
	$(DC) up -d worker

psql:
	$(DC) exec db psql -U postgres -d gst_itr_db

redis-cli:
	$(DC) exec redis redis-cli

# Run an ad-hoc command inside the app container:
# make run CMD="python -m pytest -q"
run:
	$(DC) exec app sh -lc '$(CMD)'

db-revision:
	$(DC) run --rm app alembic revision --autogenerate -m "$(MSG)"

db-upgrade:
	$(DC) run --rm app alembic upgrade head

db-downgrade:
	$(DC) run --rm app alembic downgrade $(REV)

db-history:
	$(DC) run --rm app alembic history

db-current:
	$(DC) run --rm app alembic current