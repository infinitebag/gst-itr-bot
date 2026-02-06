# 📄 CONTRIBUTING.md

```markdown
# Contributing Guide

Welcome! This project follows a **Docker-only development workflow** to ensure consistency across machines.

---

## 1. Development Philosophy

- No local Python / venv
- No OS-specific setup
- Docker = single source of truth
- One-command onboarding

---

## 2. First-Time Setup

```bash
git clone <repo>
cd gst_itr_bot
make up

That’s it.

⸻

3. Branching Strategy

Branch	Purpose
main	Production-ready
develop	Active development
feature/*	New features
fix/*	Bug fixes


⸻

4. Making Changes
	1.	Create branch

git checkout -b feature/my-change

	2.	Code changes
	3.	Rebuild incrementally

make build
make restart

	4.	Verify logs

make app-logs
make worker-logs


⸻

5. Database Changes

Schema updates
	•	Prefer migrations (Alembic if added later)
	•	For now, document SQL in PR description

Example:

ALTER TABLE sessions ADD COLUMN language TEXT;


⸻

6. Background Jobs Rules (IMPORTANT)

❌ DO NOT:

default_queue.enqueue(...)

✅ ALWAYS:

from app.workers.whatsapp import send_message

default_queue.enqueue(send_message, payload)

Reason:
	•	RQ requires a real callable
	•	Prevents startup crashes

⸻

7. Logging Rules

Use standard logging, not fastapi.logger:

import logging
logger = logging.getLogger(__name__)

logger.info("Starting worker")
logger.exception("Something failed")


⸻

8. Environment Rules
	•	.env.docker → Docker runs
	•	.env.example → committed template
	•	NEVER commit secrets

⸻

9. Code Style
	•	Black formatting
	•	Type hints encouraged
	•	Keep FastAPI startup lightweight
	•	Avoid blocking calls in request handlers

⸻

10. Testing (Optional)

If tests exist:

make run CMD="pytest -q"


⸻

11. Pull Requests

Checklist:
	•	App starts with make up
	•	No startup exceptions
	•	DB & Redis connections OK
	•	Logs are clean
	•	No secrets committed

⸻

12. When in Doubt

Reset everything:

make clean
make up


⸻

🙏 Thanks for contributing!

---

If you want, next I can:
- Align `docker-compose.yml` exactly with this README
- Add `/health` endpoint
- Add Alembic migrations
- Add CI pipeline (GitHub Actions)

Just say 👍