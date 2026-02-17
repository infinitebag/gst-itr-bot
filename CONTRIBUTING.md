# Contributing to GST + ITR WhatsApp Bot

This guide covers the full project architecture, feature inventory, setup instructions,
and development workflows. Read this before making changes.

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Feature Inventory](#feature-inventory)
5. [Quick Start](#quick-start)
6. [Environment Variables](#environment-variables)
7. [Makefile Commands](#makefile-commands)
8. [Architecture Deep Dive](#architecture-deep-dive)
9. [WhatsApp State Machine](#whatsapp-state-machine)
10. [Database Models](#database-models)
11. [Security](#security)
12. [Internationalization (i18n)](#internationalization-i18n)
13. [Adding a New Feature](#adding-a-new-feature)
14. [API Endpoints](#api-endpoints)
15. [Testing](#testing)
16. [Deployment](#deployment)
17. [Troubleshooting](#troubleshooting)

---

## Project Overview

A **FastAPI-based WhatsApp bot** for Indian tax compliance (GST and ITR),
with a CA (Chartered Accountant) dashboard. Users interact via WhatsApp to:

- Upload and parse invoices (OCR + LLM)
- File GST returns (GSTR-1, GSTR-3B, NIL filing)
- Compute ITR (ITR-1 salary, ITR-4 presumptive)
- Get AI-powered tax insights and anomaly detection
- Look up HSN codes
- Receive proactive filing deadline reminders

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | FastAPI (async) |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Cache / Sessions | Redis 7 |
| AI / NLP | OpenAI GPT-4o (intent detection, invoice parsing, tax Q&A, insights) |
| OCR | Tesseract (primary), Google Vision (planned) |
| PDF generation | ReportLab |
| WhatsApp | Meta Cloud API v20.0 |
| Voice / STT | Sarvam AI |
| Translation | Bhashini (govt) |
| Auth | JWT (CA dashboard), header token (admin) |
| Containerization | Docker + Docker Compose |
| Languages | Python 3.10+ |

---

## Project Structure

```
gst_itr_bot/
├── app/
│   ├── main.py                          # FastAPI app, lifespan, CORS, static mount
│   ├── core/
│   │   ├── config.py                    # Single Settings class + validate_secrets()
│   │   └── db.py                        # Async SQLAlchemy engine, session, health check
│   ├── db/
│   │   └── base.py                      # Canonical DeclarativeBase
│   ├── api/
│   │   ├── deps.py                      # Shared auth dependencies (timing-safe)
│   │   └── routes/
│   │       ├── __init__.py              # Router aggregation
│   │       ├── whatsapp.py              # Main webhook handler + state machine
│   │       ├── health.py                # Basic /health endpoint
│   │       ├── whatsapp_health.py       # WhatsApp token validation
│   │       ├── system_health.py         # System health dashboard
│   │       ├── admin_dashboard.py       # Dead letters + usage stats UI
│   │       ├── admin_whatsapp.py        # WhatsApp admin API (dead-letter replay)
│   │       ├── admin_analytics.py       # AI insights + anomaly API
│   │       ├── admin_invoices.py        # Invoice CRUD API
│   │       ├── admin_invoice_pdf.py     # Invoice PDF download
│   │       ├── admin_ca_dashboard.py    # CA client overview
│   │       ├── admin_ca_management.py  # CA management API
│   │       ├── admin_auth.py           # Admin authentication
│   │       ├── admin_ml_risk.py        # ML risk scoring API
│   │       ├── admin_segments.py       # Segment management API
│   │       ├── ca_auth.py              # CA JWT login/register
│   │       ├── ca_dashboard.py         # CA portal (JWT-protected)
│   │       ├── ca_gst_review.py        # CA GST review
│   │       ├── ca_itr_review.py        # CA ITR review
│   │       ├── gst_debug.py            # GST sandbox debug endpoints
│   │       ├── gst_gstr1_debug.py      # GSTR-1 debug
│   │       ├── gst_mastergst.py        # MasterGST integration
│   │       ├── gst_periods.py          # GST period management
│   │       ├── gst_annual.py           # GST annual returns (GSTR-9)
│   │       ├── itr_api.py              # ITR REST API
│   │       ├── whatsapp_health.py      # WhatsApp token validation
│   │       └── wa_handlers/            # Modular WhatsApp handler chain
│   │           ├── __init__.py         # Handler chain registry (7 modules)
│   │           ├── einvoice.py         # e-Invoice flow (Phase 6)
│   │           ├── ewaybill.py         # e-WayBill flow (Phase 6)
│   │           ├── gst_wizard.py       # Small-segment wizard (Phase 7)
│   │           ├── gst_credit_check.py # Credit check (Phase 7)
│   │           ├── multi_gstin.py      # Multi-GSTIN mgmt (Phase 8)
│   │           ├── refund_notice.py    # Refund + notice (Phase 9)
│   │           └── notification_settings.py  # Notification prefs (Phase 10)
│   ├── v1/                                # REST API v1 (mobile / web clients)
│   │   ├── __init__.py                    # v1 router aggregation
│   │   ├── deps.py                        # v1 auth dependencies
│   │   ├── envelope.py                    # Response envelope helper
│   │   ├── routes/
│   │   │   ├── auth.py                    # User registration + login + JWT
│   │   │   ├── invoices.py                # Invoice CRUD + OCR + PDF
│   │   │   ├── gst.py                     # GST GSTR-3B, GSTR-1, current period
│   │   │   ├── gst_periods.py             # GST monthly compliance
│   │   │   ├── gst_annual.py              # GST annual returns (GSTR-9)
│   │   │   ├── itr.py                     # ITR-1, ITR-2, ITR-4 computation
│   │   │   ├── analytics.py               # Tax summary, anomalies, insights
│   │   │   ├── tax_qa.py                  # Tax Q&A + HSN lookup
│   │   │   ├── ca_auth.py                 # CA login/register/refresh
│   │   │   ├── ca_clients.py              # CA client CRUD + bulk upload
│   │   │   ├── ca_reviews.py              # CA ITR/GST review workflows
│   │   │   ├── ca_deadlines.py            # CA filing deadlines
│   │   │   ├── admin_ca.py                # Admin CA management
│   │   │   ├── admin_tax_rates.py         # Admin tax rates (ITR/GST)
│   │   │   ├── knowledge.py               # RAG knowledge base
│   │   │   ├── audit.py                   # Audit trail API
│   │   │   ├── user_gstins.py             # Multi-GSTIN REST API
│   │   │   ├── refunds.py                 # Refund tracking REST API
│   │   │   ├── notices.py                 # Notice management REST API
│   │   │   └── notifications.py           # Notification REST API
│   │   └── schemas/                       # Pydantic request/response schemas
│   │       ├── auth.py, invoices.py, gst.py, periods.py, annual.py
│   │       ├── itr.py, analytics.py, tax_qa.py, ca.py
│   │       └── knowledge.py, tax_rates.py, risk.py, payment.py
│   ├── domain/
│   │   ├── i18n.py                      # All user-facing strings (6 languages)
│   │   └── services/
│   │       ├── conversation_service.py  # Conversation logic helpers
│   │       ├── gst_service.py           # GSTR-3B/GSTR-1 prep + NIL filing
│   │       ├── itr_service.py           # ITR-1 / ITR-4 computation
│   │       ├── tax_analytics.py         # Aggregation, anomalies, AI insights
│   │       ├── invoice_parser.py        # Regex + LLM invoice extraction
│   │       ├── invoice_pdf.py           # PDF generation (single + batch)
│   │       ├── intent_router.py         # NLP intent routing
│   │       ├── voice_handler.py         # Voice message -> text
│   │       ├── gstin_pan_validation.py  # GSTIN/PAN format validation
│   │       ├── health_check.py          # System health probes
│   │       ├── deadline_scheduler.py    # Background deadline reminders + NIL nudges
│   │       ├── einvoice_flow.py         # e-Invoice IRN service
│   │       ├── ewaybill_flow.py         # e-WayBill service
│   │       ├── gst_explainer.py         # Simple language tax explainer
│   │       ├── multi_gstin_service.py   # Multi-GSTIN management
│   │       ├── refund_service.py        # Refund claim tracking
│   │       ├── notice_service.py        # GST notice management
│   │       ├── notification_service.py  # Proactive notifications
│   │       ├── pii_masking.py              # PII masking for logs & replies
│   │       ├── upload_security.py          # File validation + malware scan
│   │       ├── pending_itc_service.py      # Pending ITC tracking + vendor follow-up
│   │       ├── books_vs_portal.py          # Books vs GST portal comparison
│   │       ├── audit_service.py            # Client data access audit trail
│   │       ├── ml_risk_model.py            # ML risk scoring (RandomForest + SHAP)
│   │       ├── segment_detection.py        # User segment detection
│   │       ├── feature_registry.py         # Segment-gated feature registry
│   │       ├── rag_tax_qa.py               # RAG-based tax Q&A (pgvector)
│   │       └── ca_auth.py                  # CA authentication service
│   ├── infrastructure/
│   │   ├── cache/
│   │   │   └── session_cache.py         # Redis session storage
│   │   ├── db/
│   │   │   ├── base.py                  # Re-exports canonical Base
│   │   │   ├── models.py               # All ORM models
│   │   │   └── repositories/           # Data access layer
│   │   ├── external/
│   │   │   ├── whatsapp_client.py       # Rate-limited WhatsApp sender + queue
│   │   │   ├── whatsapp_media.py        # Media download/upload/document send
│   │   │   └── openai_client.py         # OpenAI API (intent, parse, Q&A, HSN)
│   │   └── ocr/
│   │       ├── base.py                  # Abstract OCR backend
│   │       ├── tesseract_backend.py     # Tesseract implementation
│   │       ├── paddle_backend.py        # PaddleOCR implementation
│   │       └── factory.py              # OCR backend factory
│   ├── config/
│   │   └── settings.py                  # Re-exports from core/config.py
│   ├── static/
│   │   └── admin.css                    # Admin dashboard styles
│   └── templates/
│       └── admin/
│           ├── base.html                # Admin nav layout
│           ├── dead_letters.html
│           ├── usage.html
│           ├── ca_dashboard.html
│           └── system_health.html       # Health dashboard (auto-refresh)
├── alembic/                             # Database migration scripts
├── tests/                               # Test suite
├── Dockerfile
├── docker-compose.yml
├── Makefile                             # 30+ single-command targets
├── requirements-base.txt
├── requirements-dev.txt
├── requirements-prod.txt
├── alembic.ini
├── .env.example                         # Template for all env vars
└── .gitignore
```

---

## Feature Inventory

### Core Platform
| Feature | Status | Key Files |
|---|---|---|
| WhatsApp webhook (inbound/outbound) | Done | `whatsapp.py`, `whatsapp_client.py` |
| Session state machine (Redis) | Done | `session_cache.py`, `whatsapp.py` |
| Stack-based navigation (back button) | Done | `whatsapp.py` (push/pop_state) |
| Multilingual i18n (EN, HI, GU, TA, TE) | Done | `i18n.py` |
| Voice message support (Sarvam STT) | Done | `voice_handler.py` |
| NLP intent detection (GPT-4o) | Done | `intent_router.py`, `openai_client.py` |
| Webhook signature verification | Done | `whatsapp.py` |
| Rate limiting (per-user + global) | Done | `whatsapp_client.py` |
| Dead letter queue | Done | `whatsapp_client.py`, `models.py` |
| Background sender worker | Done | `whatsapp_client.py`, `main.py` |

### GST Features
| Feature | Status | Key Files |
|---|---|---|
| GSTIN validation (format + checksum) | Done | `gstin_pan_validation.py` |
| Invoice OCR (Tesseract) | Done | `tesseract_backend.py` |
| Invoice LLM parsing (GPT-4o) | Done | `openai_client.py` |
| Single invoice upload + parse | Done | `whatsapp.py` |
| Batch invoice upload | Done | `whatsapp.py` |
| GSTR-3B preparation | Done | `gst_service.py` |
| GSTR-1 preparation | Done | `gst_service.py` |
| NIL GST filing (one-click) | Done | `gst_service.py`, `whatsapp.py` |
| NIL filing proactive nudge | Done | `deadline_scheduler.py` |
| Invoice PDF generation + WhatsApp send | Done | `invoice_pdf.py`, `whatsapp_media.py` |
| HSN code lookup (GPT-4o) | Done | `openai_client.py`, `whatsapp.py` |
| MasterGST sandbox integration | Done | `gst_mastergst.py` |

### ITR Features
| Feature | Status | Key Files |
|---|---|---|
| ITR-1 (salary) conversational flow | Done | `itr_service.py`, `whatsapp.py` |
| ITR-4 (presumptive) conversational flow | Done | `itr_service.py`, `whatsapp.py` |
| Old vs New regime comparison | Done | `itr_service.py` |
| Deductions (80C, 80D, 80E) | Done | `itr_service.py` |

### Analytics and Insights
| Feature | Status | Key Files |
|---|---|---|
| Tax summary aggregation | Done | `tax_analytics.py` |
| Anomaly detection | Done | `tax_analytics.py` |
| AI-powered insights (GPT-4o) | Done | `tax_analytics.py` |
| Filing deadline tracking | Done | `tax_analytics.py` |
| Tax Q&A (conversational) | Done | `openai_client.py`, `whatsapp.py` |

### Proactive Notifications
| Feature | Status | Key Files |
|---|---|---|
| Filing deadline reminders | Done | `deadline_scheduler.py` |
| Overdue alerts | Done | `deadline_scheduler.py` |
| NIL filing nudges | Done | `deadline_scheduler.py` |
| Redis deduplication | Done | `deadline_scheduler.py` |

### Admin and Monitoring
| Feature | Status | Key Files |
|---|---|---|
| System health dashboard (HTML + JSON) | Done | `health_check.py`, `system_health.py` |
| Dead letter management | Done | `admin_dashboard.py`, `admin_whatsapp.py` |
| Usage stats | Done | `admin_dashboard.py` |
| Invoice management API | Done | `admin_invoices.py` |
| Invoice PDF export | Done | `admin_invoice_pdf.py` |
| CA client overview | Done | `admin_ca_dashboard.py` |
| Analytics API (insights, anomalies) | Done | `admin_analytics.py` |

### CA Portal (JWT-Protected)
| Feature | Status | Key Files |
|---|---|---|
| CA registration + login | Done | `ca_auth.py` |
| JWT access + refresh tokens | Done | `ca_auth.py` |
| Client management | Done | `ca_dashboard.py` |
| Client filing status | Done | `ca_dashboard.py` |

### Phase 6: e-Invoice & e-WayBill Flows
| Feature | Status | Key Files |
|---|---|---|
| e-Invoice menu + upload + confirm | Done | `wa_handlers/einvoice.py`, `einvoice_flow.py` |
| e-Invoice status check + cancel | Done | `wa_handlers/einvoice.py` |
| e-WayBill menu + upload + transport | Done | `wa_handlers/ewaybill.py`, `ewaybill_flow.py` |
| e-WayBill tracking + vehicle update | Done | `wa_handlers/ewaybill.py` |
| Upload routing for e-Invoice/e-WayBill | Done | `whatsapp.py` |

### Phase 7: Segment-Differentiated Filing
| Feature | Status | Key Files |
|---|---|---|
| Small-segment guided wizard (sales → purchases → summary) | Done | `wa_handlers/gst_wizard.py`, `gst_explainer.py` |
| Medium-segment credit check (2B import + reconciliation) | Done | `wa_handlers/gst_credit_check.py` |
| Credit check result + mismatch details | Done | `wa_handlers/gst_credit_check.py` |
| Simple language tax explainer | Done | `gst_explainer.py` |

### Phase 8: Multi-GSTIN Management
| Feature | Status | Key Files |
|---|---|---|
| Multi-GSTIN menu + add + label | Done | `wa_handlers/multi_gstin.py`, `multi_gstin_service.py` |
| GSTIN switch + summary view | Done | `wa_handlers/multi_gstin.py` |
| UserGSTIN DB model + migration | Done | `models.py`, `alembic/` |
| Multi-GSTIN REST API (5 endpoints) | Done | `v1/routes/user_gstins.py` |

### Phase 9: Refund, Notice & Export
| Feature | Status | Key Files |
|---|---|---|
| Refund tracking (create + list claims) | Done | `wa_handlers/refund_notice.py`, `refund_service.py` |
| Refund types (excess, export, inverted duty) | Done | `refund_service.py` |
| GST notice management (list + upload) | Done | `wa_handlers/refund_notice.py`, `notice_service.py` |
| Export services placeholder | Done | `wa_handlers/refund_notice.py` |
| Refund REST API (3 endpoints) | Done | `v1/routes/refunds.py` |
| Notice REST API (3 endpoints) | Done | `v1/routes/notices.py` |

### Phase 10: Proactive Notifications
| Feature | Status | Key Files |
|---|---|---|
| Notification preferences (WhatsApp) | Done | `wa_handlers/notification_settings.py` |
| Notification scheduling service | Done | `notification_service.py` |
| Filing reminder scheduling | Done | `notification_service.py` |
| Notification REST API (4 endpoints) | Done | `v1/routes/notifications.py` |

### Architectural: Modular Handler Chain
| Feature | Status | Key Files |
|---|---|---|
| wa_handlers/ module directory | Done | `wa_handlers/__init__.py` |
| Handler chain dispatch in webhook | Done | `whatsapp.py` |
| 7 handler modules (einvoice, ewaybill, wizard, credit, multi-gstin, refund, notifications) | Done | `wa_handlers/*.py` |

### ML Risk Scoring
| Feature | Status | Key Files |
|---|---|---|
| RandomForest-based risk assessment | Done | `ml_risk_model.py`, `admin_ml_risk.py` |
| SHAP explainability for risk factors | Done | `ml_risk_model.py` |
| Rule-based fallback (cold start) | Done | `ml_risk_model.py` |
| Configurable blend weight (rules ↔ ML) | Done | `config.py` |
| Auto-retrain on new labeled data | Done | `ml_retrain_job.py` |

### RAG Knowledge Base
| Feature | Status | Key Files |
|---|---|---|
| Document ingestion + chunking | Done | `rag_tax_qa.py`, `embedding_jobs.py` |
| pgvector similarity search | Done | `rag_tax_qa.py` |
| Knowledge base CRUD REST API | Done | `v1/routes/knowledge.py` |
| Configurable embedding model + dimensions | Done | `config.py` |

### Segment Gating
| Feature | Status | Key Files |
|---|---|---|
| Auto segment detection (small/medium/enterprise) | Done | `segment_detection.py` |
| Feature registry per segment | Done | `feature_registry.py` |
| Dynamic WhatsApp menus by segment | Done | `whatsapp_menu_builder.py` |
| Admin segment management API | Done | `admin_segments.py` |

### OTP / Email Verification
| Feature | Status | Key Files |
|---|---|---|
| Email-based OTP sending (SMTP) | Done | `otp_service.py` |
| Configurable SMTP settings | Done | `config.py` |

### Security & Compliance
| Feature | Status | Key Files |
|---|---|---|
| PII masking (GSTIN, PAN, phone, bank) | Done | `pii_masking.py` |
| Upload malware scanning + file validation | Done | `upload_security.py` |
| Global commands (help, restart, talk_to_ca) | Done | `whatsapp.py`, `i18n.py` |
| GSTR-2B PDF/Excel import | Done | `gstr2b_service.py` |
| Pending ITC tracking + vendor follow-up | Done | `pending_itc_service.py` |
| Books vs Portal comparison (sales + purchases) | Done | `books_vs_portal.py` |
| Client data access audit trail | Done | `audit_service.py`, `v1/routes/audit.py` |
| User-friendly i18n menu labels | Done | `i18n.py` |

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
# One command to rule them all:
make first-run

# This will:
# 1. Create .env.docker from .env.example
# 2. Build all Docker containers (app, worker, db, redis)
# 3. Wait for PostgreSQL + Redis health checks
# 4. Run Alembic database migrations
# 5. Print all URLs

# Then edit your API keys:
vim .env.docker     # Fill in WHATSAPP_*, OPENAI_API_KEY, etc.
make restart        # Restart with new keys
make tunnel         # Start Cloudflare Tunnel (your-domain → localhost:8000)
```

### Option 2: Local Development

```bash
# 1. Create virtual environment
python3 -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements-dev.txt

# 3. Install Tesseract
brew install tesseract          # macOS
sudo apt install tesseract-ocr  # Ubuntu

# 4. Start PostgreSQL + Redis (via Docker)
docker run -d --name gst-postgres -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=gst_itr_db \
  -p 5432:5432 postgres:16-alpine

docker run -d --name gst-redis -p 6379:6379 redis:7-alpine

# 5. Configure environment
cp .env.example .env.local
vim .env.local     # Fill in your API keys

# 6. Run migrations
alembic upgrade head

# 7. Start the app
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Post-Startup Verification

| Check | URL / Command |
|---|---|
| App running | `curl http://localhost:8000/health` |
| Health dashboard | http://localhost:8000/admin/system-health |
| Health JSON | `curl http://localhost:8000/admin/system-health/json` |
| Admin usage | http://localhost:8000/admin/ui/usage |
| CA portal | http://localhost:8000/ca/auth/login |

---

## Environment Variables

All config is in `.env.example`. Copy it to `.env.local` (local dev) or `.env.docker`
(Docker). Critical variables:

### Required for Core Functionality
| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL async connection string |
| `REDIS_URL` | Redis connection string |
| `WHATSAPP_VERIFY_TOKEN` | Your webhook verification token |
| `WHATSAPP_ACCESS_TOKEN` | Meta Cloud API access token |
| `WHATSAPP_PHONE_NUMBER_ID` | From Meta API Setup page |
| `WHATSAPP_APP_SECRET` | App secret for webhook signature verification |
| `OPENAI_API_KEY` | OpenAI API key (powers all AI features) |

### Required for Security
| Variable | Description |
|---|---|
| `CA_JWT_SECRET` | JWT signing secret (MUST change from default in prod) |
| `ADMIN_API_KEY` | Admin API token (MUST change from default in prod) |
| `ADMIN_JWT_SECRET` | Admin JWT secret (MUST change from default in prod) |
| `USER_JWT_SECRET` | User API JWT secret (MUST change from default in prod) |

### RAG / ML / Segments (Optional — have sensible defaults)
| Variable | Description |
|---|---|
| `EMBEDDING_MODEL` | OpenAI embedding model (default: `text-embedding-3-small`) |
| `RAG_TOP_K` | Top-K retrieval results (default: 5) |
| `ML_RISK_ENABLED` | Enable ML risk scoring (default: `true`) |
| `ML_RISK_BLEND_WEIGHT` | Rule vs ML blend (default: 0.3) |
| `SEGMENT_GATING_ENABLED` | Enable segment-based menus (default: `true`) |
| `DEFAULT_SEGMENT` | Default segment (default: `small`) |
| `NOTIFICATION_ENABLED` | Enable proactive notifications (default: `true`) |

### OTP / Email (Optional)
| Variable | Description |
|---|---|
| `OTP_EMAIL_ENABLED` | Enable email OTP (default: `false`) |
| `OTP_SMTP_HOST` | SMTP server (e.g. `smtp.gmail.com`) |
| `OTP_FROM_EMAIL` | Sender email address |

### Other Optional Services
| Variable | Description |
|---|---|
| `SARVAM_API_KEY` | Sarvam STT for voice messages |
| `BHASHINI_API_KEY` | Bhashini translation API |
| `MASTERGST_*` | MasterGST sandbox/production credentials |
| `OPENAI_MODEL` | Model name (default: `gpt-4o`) |
| `OCR_BACKEND` | `tesseract` (default) or `google_vision` |

### Startup Validation

The app validates secrets on startup:
- **Dev mode** (`ENV=dev`): Logs warnings for unsafe defaults
- **Production** (`ENV=production`): **Crashes** if `CA_JWT_SECRET`, `ADMIN_API_KEY`,
  or `WHATSAPP_APP_SECRET` still have default values

---

## Makefile Commands

Run `make help` to see all 30+ targets. Key ones:

### Quick Start
```bash
make first-run       # Full first-time setup (build + migrate + start)
make setup           # Create .env.docker from template
```

### Docker Lifecycle
```bash
make up              # Build + start all services
make down            # Stop all containers
make restart         # Restart app + worker
make rebuild         # Full rebuild (no Docker cache)
make clean           # Stop + DELETE all data (confirms first)
```

### Database
```bash
make db-upgrade                    # Apply pending migrations
make db-revision MSG='add xyz'     # Generate new migration
make db-reset                      # Drop + re-migrate (confirms first)
make db-history                    # Show migration history
make psql                          # Open PostgreSQL shell
```

### Monitoring
```bash
make health          # Open health dashboard in browser
make health-json     # Fetch health JSON via curl
make logs            # Follow all container logs
make app-logs        # Follow app logs only
```

### Code Quality
```bash
make lint            # Run ruff linter
make fmt             # Auto-format with ruff
make check           # Lint + format check (CI-friendly)
make compile-check   # Verify all .py files compile
make test            # Run pytest
make test-cov        # Run pytest with coverage
```

### Utilities
```bash
make env-check       # Validate required env vars are set
make seed-ca         # Create test CA user (admin@example.com / admin123)
make tunnel          # Start Cloudflare Tunnel (your-domain → localhost:8000)
make tunnel-ngrok    # Start ngrok tunnel (local dev fallback)
make redis-cli       # Open Redis CLI
```

---

## Architecture Deep Dive

### Layer Separation

```
+---------------------------------------------+
|                  API Layer                   |
|  routes/whatsapp.py  routes/admin_*.py       |
|  routes/ca_*.py      routes/system_health.py |
|  routes/wa_handlers/ (7 modular handlers)    |
|  v1/routes/ (20 route modules, 14 schemas)   |
|    auth, invoices, gst, itr, analytics,      |
|    tax_qa, ca_*, admin_*, knowledge, audit,  |
|    user_gstins, refunds, notices, notifs     |
+---------------------------------------------+
|              Domain Layer                    |
|  services/gst_service.py                     |
|  services/itr_service.py                     |
|  services/tax_analytics.py                   |
|  services/invoice_pdf.py                     |
|  services/deadline_scheduler.py              |
|  services/einvoice_flow.py  (Phase 6)        |
|  services/ewaybill_flow.py  (Phase 6)        |
|  services/gst_explainer.py  (Phase 7)        |
|  services/multi_gstin_service.py (Phase 8)   |
|  services/refund_service.py (Phase 9)        |
|  services/notice_service.py (Phase 9)        |
|  services/notification_service.py (Phase 10) |
|  services/pii_masking.py                   |
|  services/upload_security.py               |
|  services/pending_itc_service.py           |
|  services/books_vs_portal.py               |
|  services/audit_service.py                 |
|  services/ml_risk_model.py   (ML scoring)  |
|  services/segment_detection.py             |
|  services/feature_registry.py              |
|  services/rag_tax_qa.py     (RAG/pgvector) |
|  i18n.py                                     |
+---------------------------------------------+
|           Infrastructure Layer               |
|  external/whatsapp_client.py  (rate-limited) |
|  external/openai_client.py    (singleton)    |
|  cache/session_cache.py       (Redis)        |
|  db/models.py + repositories/ (PostgreSQL)   |
|  ocr/tesseract_backend.py                    |
+---------------------------------------------+
|              Core Layer                      |
|  core/config.py  (Settings + validation)     |
|  core/db.py      (engine + sessions)         |
|  db/base.py      (DeclarativeBase)           |
+---------------------------------------------+
```

### Key Design Patterns

| Pattern | Where | Notes |
|---|---|---|
| **State machine** | `whatsapp.py` | String-based states + stack navigation |
| **Queue + Worker** | `whatsapp_client.py` | Async queue, exponential backoff, dead-letter |
| **Singleton** | `openai_client.py` | Lazy-initialized global client |
| **Factory** | `ocr/factory.py` | OCR backend selection via config |
| **Repository** | `infrastructure/db/repositories/` | Data access abstraction |
| **Dependency injection** | `api/deps.py` | Shared FastAPI dependencies |
| **Pure functions** | `tax_analytics.py`, `invoice_pdf.py` | No side effects, testable |
| **Graceful degradation** | `openai_client.py`, `tax_analytics.py` | AI fallback to non-AI |
| **PII masking** | `pii_masking.py` | Regex-based detection + replacement for GSTIN, PAN, phone, bank |
| **File validation** | `upload_security.py` | Magic bytes, MIME checks, PDF malware scanning |

### Background Workers

Two `asyncio.create_task` workers run in the FastAPI lifespan:

1. **WhatsApp Sender Worker** (`whatsapp_client.py`)
   - Drains `_outgoing_queue` continuously
   - Per-user rate limit: 30/min, 1000/day
   - Global rate limit: 4 msg/sec
   - Exponential backoff on failure (3 retries)
   - Dead-letter on exhaustion

2. **Deadline Reminder Loop** (`deadline_scheduler.py`)
   - Runs every 6 hours
   - Sends filing deadline reminders (GSTR-1: 11th, GSTR-3B: 20th)
   - Sends NIL filing nudges (users with GSTIN but no invoices)
   - Redis-based deduplication (one reminder per user per deadline)

---

## WhatsApp State Machine

```
                    +---------------+
                    |  MAIN_MENU    |  <-- "0" from any state
                    +-------+-------+
                            |
              +-------------+-------------+
              |             |             |
        +-----v-----+ +----v----+ +------v------+
        | GST_MENU  | |ITR_MENU | |  TAX_QA     |
        +-----+-----+ +----+----+ +-------------+
              |             |
    +---------+-----+  +----+----------+
    |         |     |  |    |          |
+---v---+ +--v---+ | +v----v---+ +----v------+
|GSTIN  | |FILE  | | |ITR1     | |ITR4       |
|VALID  | |MENU  | | |(5 step) | |(4 step)   |
+-------+ +--+---+ | +---------+ +-----------+
              |     |
     +--------+-----+
     |        |     |
+----v---++--v---++v-----------+
|GSTR-3B ||NIL   ||UPLOAD      |
| prep   ||FILE  ||(single/    |
+--------+|MENU  || batch)     |
          +--+---++-----------+
             |
       +-----v-------+
       |NIL_CONFIRM   |
       +--------------+

Special keywords (work from any state):
  "0" -> Reset to MAIN_MENU
  "9" -> Go back (pop stack)
  "NIL" -> Jump to NIL filing
  "help" / "?" -> Show quick command reference
  "restart" -> Clear session, return to MAIN_MENU
  "ca" / "talk to ca" -> Request CA handoff
```

### States

| State | Description |
|---|---|
| `MAIN_MENU` | Welcome screen with 6 options |
| `GST_MENU` | GST services (validate, upload, file, NIL, analytics) |
| `WAIT_GSTIN` | Waiting for GSTIN input |
| `GST_FILING_MENU` | Choose filing type (GSTR-3B, GSTR-1, NIL) |
| `NIL_FILING_MENU` | Choose NIL form (GSTR-3B, GSTR-1, Both) |
| `NIL_FILING_CONFIRM` | Confirm NIL filing |
| `WAIT_INVOICE_UPLOAD` | Waiting for invoice image/PDF |
| `BATCH_UPLOAD` | Multi-invoice batch mode |
| `ITR_MENU` | Choose ITR type (ITR-1, ITR-4) |
| `ITR1_ASK_SALARY` | ITR-1 step 1: salary input |
| `ITR1_ASK_OTHER_INCOME` | ITR-1 step 2: other income |
| `ITR1_ASK_80C` | ITR-1 step 3: 80C deductions |
| `ITR1_ASK_80D` | ITR-1 step 4: 80D deductions |
| `ITR1_ASK_TDS` | ITR-1 step 5: TDS already paid |
| `ITR4_ASK_TYPE` | ITR-4 step 1: business vs profession |
| `ITR4_ASK_TURNOVER` | ITR-4 step 2: turnover |
| `ITR4_ASK_80C` | ITR-4 step 3: 80C deductions |
| `ITR4_ASK_TDS` | ITR-4 step 4: TDS already paid |
| `TAX_QA` | Conversational tax Q&A |
| `INSIGHTS_MENU` | Tax analytics and insights |
| `HSN_LOOKUP` | HSN code search |
| `LANG_MENU` | Language selection |
| **Phase 6: e-Invoice** | |
| `EINVOICE_MENU` | e-Invoice options (generate/status/cancel) |
| `EINVOICE_UPLOAD` | Upload invoice for IRN generation |
| `EINVOICE_CONFIRM` | Confirm IRN generation |
| `EINVOICE_STATUS_ASK` | Enter IRN to check status |
| `EINVOICE_CANCEL` | Cancel IRN flow |
| **Phase 6: e-WayBill** | |
| `EWAYBILL_MENU` | e-WayBill options (generate/track/vehicle) |
| `EWAYBILL_UPLOAD` | Upload invoice for EWB |
| `EWAYBILL_TRANSPORT` | Enter transport details |
| `EWAYBILL_TRACK_ASK` | Enter EWB number to track |
| `EWAYBILL_VEHICLE_ASK` | Update vehicle info |
| **Phase 7: Segment Flows** | |
| `SMALL_WIZARD_SALES` | Wizard: upload sales invoices |
| `SMALL_WIZARD_PURCHASES` | Wizard: upload purchase invoices |
| `SMALL_WIZARD_CONFIRM` | Wizard: confirm summary / send to CA |
| `MEDIUM_CREDIT_CHECK` | Auto credit check (2B import + reconciliation) |
| `MEDIUM_CREDIT_RESULT` | Show credit check results + actions |
| `GST_FILING_STATUS` | GST filing status view |
| **Phase 8: Multi-GSTIN** | |
| `MULTI_GSTIN_MENU` | List GSTINs, add/switch/summary |
| `MULTI_GSTIN_ADD` | Enter new GSTIN |
| `MULTI_GSTIN_LABEL` | Label the new GSTIN |
| `MULTI_GSTIN_SUMMARY` | Consolidated summary view |
| **Phase 9: Refund & Notices** | |
| `REFUND_MENU` | Refund options (new/track) |
| `REFUND_TYPE` | Select refund type |
| `REFUND_DETAILS` | Enter refund amount |
| `NOTICE_MENU` | Notice options (list/upload) |
| `NOTICE_UPLOAD` | Upload notice document |
| `EXPORT_MENU` | Export services |
| **Phase 10: Notifications** | |
| `NOTIFICATION_SETTINGS` | Set notification preferences |

---

## Database Models

| Model | Table | Description |
|---|---|---|
| `User` | `users` | Core user (UUID PK, whatsapp_number unique) |
| `Session` | `sessions` | Conversation state (step, language, active) |
| `Invoice` | `invoices` | Tax invoices (GSTIN, tax breakdown, B2B/B2C) |
| `WhatsAppMessageLog` | `whatsapp_message_logs` | Audit log (sent/dropped/failed) |
| `WhatsAppDeadLetter` | `whatsapp_dead_letters` | Failed messages for replay |
| `CAUser` | `ca_users` | Chartered Accountant users (email, JWT) |
| `BusinessClient` | `business_clients` | CA's client roster (FK to ca_users) |
| `Feature` | `features` | Segment-gated feature definitions |
| `SegmentFeature` | `segment_features` | Feature visibility per segment |
| `UserGSTIN` | `user_gstins` | Multi-GSTIN management per user |
| `RefundClaim` | `refund_claims` | GST refund claim tracking |
| `GSTNotice` | `gst_notices` | GST notice management |
| `NotificationSchedule` | `notification_schedules` | Proactive notification scheduling |
| `ReturnPeriod` | `return_periods` | GST return period tracking |
| `Gstr2bInvoice` | `gstr2b_invoices` | GSTR-2B imported invoices |
| `ReconciliationResult` | `reconciliation_results` | Invoice reconciliation results |
| `RiskAssessment` | `risk_assessments` | ML-based risk scoring |

### Migrations

```bash
# After changing models:
make db-revision MSG='describe your change'

# Apply:
make db-upgrade

# Rollback one step:
make db-downgrade REV='-1'
```

---

## Security

### Measures in Place

| Protection | Implementation |
|---|---|
| Webhook signature | HMAC-SHA256 via `WHATSAPP_APP_SECRET` |
| Admin auth | Timing-safe `hmac.compare_digest` in `api/deps.py` |
| CA auth | JWT with httpOnly cookies, bcrypt password hashing |
| Secrets validation | Startup crash if defaults used in production |
| CORS | `CORSMiddleware` (restrictive in prod, permissive in dev) |
| Rate limiting | Per-user (30/min, 1000/day) + global (4 msg/sec) |
| Dead letter | Failed messages stored for audit, not lost |
| PII masking | Auto-mask GSTIN, PAN, phone, bank accounts in logs via `pii_masking.py` |
| Upload scanning | File size, MIME, magic bytes, PDF malware patterns via `upload_security.py` |
| Audit trail | Client data access logging with in-memory buffer via `audit_service.py` |

### Important Security Notes

- **Never commit `.env` files** (`.gitignore` excludes them)
- Run `make env-check` to verify all secrets are properly set
- In production, set `ENV=production` to enable strict validation
- `CA_JWT_SECRET` and `ADMIN_API_KEY` MUST be changed from defaults
- Webhook signature verification is **enforced** in non-dev environments
- All admin token comparisons use constant-time `hmac.compare_digest`

---

## Internationalization (i18n)

### Supported Languages

| Code | Language |
|---|---|
| `en` | English |
| `hi` | Hindi |
| `gu` | Gujarati |
| `ta` | Tamil |
| `te` | Telugu |

### How It Works

All user-facing strings are in `app/domain/i18n.py`:

```python
MESSAGES = {
    "WELCOME_MENU": {
        "en": "Welcome to GST + ITR Bot\n...",
        "hi": "GST + ITR ....",
        ...
    },
}
```

Usage in handlers:

```python
from app.domain.i18n import t as i18n_t

text = i18n_t("WELCOME_MENU", lang="hi")
```

### Adding a New Language

1. Add the language code to `SUPPORTED_LANGS` in `i18n.py`
2. Add the display name to `LANG_NAMES`
3. Add translations for ALL keys in `MESSAGES`
4. Update `LANG_NUMBER_MAP` in `whatsapp.py`

---

## Adding a New Feature

### 1. New WhatsApp Conversational Flow

```python
# Step 1: Add state constants to whatsapp.py
TDS_MENU = "TDS_MENU"
TDS_ASK_AMOUNT = "TDS_ASK_AMOUNT"

# Step 2: Add i18n keys to i18n.py (all 6 languages)
# "TDS_MENU": {"en": "...", "hi": "...", "gu": "...", "ta": "...", "te": "..."}

# Step 3: Add state handlers in whatsapp.py
# elif state == TDS_MENU:
#     ...

# Step 4: Add service logic to domain/services/
# Step 5: Wire menu option in MAIN_MENU or GST_MENU handler
# Step 6: Update _state_to_screen_key() mapping
```

### 2. New Admin API Endpoint

```python
# In a new or existing admin route file:
from app.api.deps import require_admin_token

@router.get("/my-endpoint", dependencies=[Depends(require_admin_token)])
async def my_endpoint():
    ...
```

### 3. New Database Model

1. Add model to `app/infrastructure/db/models.py`
2. Generate migration: `make db-revision MSG='add my_table'`
3. Apply: `make db-upgrade`

### 4. Development Workflow

```bash
# Create feature branch
git checkout -b feature/my-change

# Make changes, then rebuild
make build && make restart

# Check logs
make app-logs

# Verify compilation
make compile-check

# Run linter
make lint

# Run tests
make test
```

---

## API Endpoints

### Public
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Basic health check |
| `GET` | `/webhook` | WhatsApp webhook verification |
| `POST` | `/webhook` | WhatsApp inbound messages |

### Admin (X-Admin-Token header required)
| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/system-health` | System health dashboard (HTML) |
| `GET` | `/admin/system-health/json` | System health (JSON) |
| `GET` | `/admin/ui/dead-letters` | Dead letter UI |
| `GET` | `/admin/ui/usage` | Usage stats UI |
| `GET` | `/admin/whatsapp/dead-letters` | Dead letters API |
| `POST` | `/admin/whatsapp/dead-letters/{id}/replay` | Replay dead letter |
| `POST` | `/admin/invoices` | Create invoice |
| `GET` | `/admin/invoices/{number}` | List invoices |
| `GET` | `/admin/invoices/{id}/summary.pdf` | Invoice PDF |
| `GET` | `/admin/ca/dashboard` | CA overview |
| `GET` | `/admin/analytics/insights/{number}` | AI insights |
| `GET` | `/admin/analytics/anomalies/{number}` | Anomaly report |
| `GET` | `/admin/analytics/deadlines` | Filing deadlines |

### CA Portal (JWT cookie required)
| Method | Path | Description |
|---|---|---|
| `POST` | `/ca/auth/register` | Register CA user |
| `POST` | `/ca/auth/login` | Login (returns JWT) |
| `POST` | `/ca/auth/refresh` | Refresh token |
| `GET` | `/ca/dashboard/*` | CA dashboard routes |
| `GET` | `/ca/gst-review/` | List GST filings for review |
| `POST` | `/ca/gst-review/{id}/approve` | Approve GST filing |
| `GET` | `/ca/itr-review/` | List ITR drafts for review |
| `POST` | `/ca/itr-review/{id}/approve` | Approve ITR draft |

### v1 REST API — User Auth (JWT required)
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/auth/register` | User registration |
| `POST` | `/api/v1/auth/login` | User login |
| `POST` | `/api/v1/auth/refresh` | Refresh JWT token |
| `GET` | `/api/v1/auth/me` | Current user profile |
| `POST` | `/api/v1/auth/link-whatsapp` | Link WhatsApp number |

### v1 REST API — Invoices
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/invoices/` | List invoices (paginated) |
| `POST` | `/api/v1/invoices/` | Create invoice |
| `GET` | `/api/v1/invoices/{id}` | Get invoice details |
| `GET` | `/api/v1/invoices/{id}/summary.pdf` | Download invoice PDF |

### v1 REST API — GST
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/gst/current-period` | Current GST period |
| `POST` | `/api/v1/gst/gstr3b-prep` | Prepare GSTR-3B |
| `POST` | `/api/v1/gst/gstr1-prep` | Prepare GSTR-1 |
| `POST` | `/api/v1/gst/nil-filing` | File NIL return |
| `GET` | `/api/v1/gst/summary` | GST summary |

### v1 REST API — GST Periods
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/gst/periods/` | List return periods |
| `POST` | `/api/v1/gst/periods/` | Create return period |
| `GET` | `/api/v1/gst/periods/{id}` | Get period details |
| `PUT` | `/api/v1/gst/periods/{id}` | Update period |
| `POST` | `/api/v1/gst/periods/{id}/lock` | Lock filing period |

### v1 REST API — GST Annual (GSTR-9)
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/gst/annual/` | List annual returns |
| `POST` | `/api/v1/gst/annual/` | Create annual return |
| `GET` | `/api/v1/gst/annual/{id}` | Get annual details |
| `POST` | `/api/v1/gst/annual/{id}/transition` | Status transition |

### v1 REST API — ITR
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/itr/compute-itr1` | Compute ITR-1 (Sahaj) |
| `POST` | `/api/v1/itr/compute-itr2` | Compute ITR-2 (Capital Gains) |
| `POST` | `/api/v1/itr/compute-itr4` | Compute ITR-4 (Sugam) |
| `GET` | `/api/v1/itr/result/{id}` | Get computation result |

### v1 REST API — Analytics
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/analytics/summary` | Tax summary aggregation |
| `GET` | `/api/v1/analytics/anomalies` | Anomaly detection report |
| `GET` | `/api/v1/analytics/deadlines` | Filing deadline tracking |
| `POST` | `/api/v1/analytics/insights` | AI-powered insights |

### v1 REST API — Tax Q&A
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/tax-qa/question` | Ask a tax question |
| `POST` | `/api/v1/tax-qa/hsn-lookup` | HSN/SAC code lookup |

### v1 REST API — CA Auth
| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/ca/auth/login` | CA login |
| `POST` | `/api/v1/ca/auth/register` | CA registration |
| `POST` | `/api/v1/ca/auth/refresh` | Refresh JWT token |
| `GET` | `/api/v1/ca/auth/me` | Current CA profile |

### v1 REST API — CA Clients
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/ca/clients/` | List CA's clients |
| `POST` | `/api/v1/ca/clients/` | Add client |
| `GET` | `/api/v1/ca/clients/bulk-upload/template` | CSV template |
| `POST` | `/api/v1/ca/clients/bulk-upload` | Bulk upload clients |
| `GET` | `/api/v1/ca/clients/{id}` | Get client details |
| `PUT` | `/api/v1/ca/clients/{id}` | Update client |
| `GET` | `/api/v1/ca/clients/{id}/analytics` | Client analytics |

### v1 REST API — CA Reviews
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/ca/itr-reviews` | List ITR drafts for review |
| `POST` | `/api/v1/ca/itr-reviews/{id}/approve` | Approve ITR |
| `POST` | `/api/v1/ca/itr-reviews/{id}/request-changes` | Request changes |
| `GET` | `/api/v1/ca/gst-reviews` | List GST filings for review |
| `POST` | `/api/v1/ca/gst-reviews/{id}/approve` | Approve GST |
| `POST` | `/api/v1/ca/gst-reviews/{id}/submit-mastergst` | Submit to MasterGST |

### v1 REST API — Admin CA (X-Admin-Token required)
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/admin/ca/list` | List all CAs |
| `GET` | `/api/v1/admin/ca/pending` | Pending CA approvals |
| `POST` | `/api/v1/admin/ca/{id}/approve` | Approve CA |
| `POST` | `/api/v1/admin/ca/{id}/reject` | Reject CA |
| `POST` | `/api/v1/admin/ca/{id}/toggle-active` | Enable/disable CA |

### v1 REST API — Admin Tax Rates (X-Admin-Token required)
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/admin/tax-rates/itr/{year}` | Get ITR tax rates |
| `GET` | `/api/v1/admin/tax-rates/gst` | Get GST rates |
| `POST` | `/api/v1/admin/tax-rates/itr/refresh` | Refresh ITR rates |
| `POST` | `/api/v1/admin/tax-rates/gst/refresh` | Refresh GST rates |

### v1 REST API — Knowledge Base
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/knowledge/` | Search knowledge base |
| `POST` | `/api/v1/knowledge/` | Add knowledge entry |
| `GET` | `/api/v1/knowledge/{doc_id}` | Get document |
| `DELETE` | `/api/v1/knowledge/{doc_id}` | Delete document |

### v1 REST API — Multi-GSTIN
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/user-gstins/` | List user's GSTINs |
| `POST` | `/api/v1/user-gstins/` | Add a GSTIN |
| `DELETE` | `/api/v1/user-gstins/{gstin}` | Remove a GSTIN |
| `PUT` | `/api/v1/user-gstins/primary` | Set primary GSTIN |
| `GET` | `/api/v1/user-gstins/summary` | Consolidated GSTIN summary |

### v1 REST API — Refunds
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/refunds/` | List refund claims |
| `POST` | `/api/v1/refunds/` | Create refund claim |
| `GET` | `/api/v1/refunds/{claim_id}` | Get refund claim details |

### v1 REST API — Notices
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/notices/` | List GST notices |
| `POST` | `/api/v1/notices/` | Create/record a notice |
| `PUT` | `/api/v1/notices/{notice_id}` | Update notice status |

### v1 REST API — Notifications
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/notifications/preferences` | Get notification preferences |
| `PUT` | `/api/v1/notifications/preferences` | Update notification preferences |
| `GET` | `/api/v1/notifications/scheduled` | List scheduled notifications |
| `POST` | `/api/v1/notifications/schedule-reminders` | Trigger reminder scheduling |

### v1 REST API — Audit (Admin token required)
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/audit/recent` | Recent audit entries (with filters) |
| `GET` | `/api/v1/audit/client/{gstin}` | Access summary for a GSTIN |

---

## Testing

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run specific test file
make run CMD='python -m pytest tests/test_itr.py -v'
```

---

## Deployment

### Docker Compose (Recommended)

```bash
# Production deployment
ENV_FILE=.env.production make up

# Start Cloudflare Tunnel (permanent webhook at your domain)
make tunnel

# Or install as system service (auto-starts on boot)
sudo cloudflared service install
```

### Pre-Deployment Checklist

- [ ] `ENV=production` set (enables strict secret validation)
- [ ] `CA_JWT_SECRET` changed (use `openssl rand -hex 32`)
- [ ] `ADMIN_API_KEY` changed from default
- [ ] `WHATSAPP_APP_SECRET` set for webhook verification
- [ ] `OPENAI_API_KEY` set
- [ ] `WHATSAPP_ACCESS_TOKEN` is a permanent token (not temporary)
- [ ] Run `make env-check` to verify all above
- [ ] Database migrations applied (`make db-upgrade`)

### WhatsApp Webhook Setup

1. Go to [Meta Developer Console](https://developers.facebook.com)
2. Select your app > WhatsApp > Configuration
3. Set **Callback URL**: `https://your-domain.com/webhook` (your Cloudflare Tunnel or ngrok URL)
4. Set **Verify Token**: same as `WHATSAPP_VERIFY_TOKEN` in `.env`
5. Subscribe to: `messages`, `messaging_postbacks`

---

## Troubleshooting

### App won't start

```bash
# Check container status
make ps

# Check app logs
make app-logs

# Common issues:
# - DB not ready: Wait for health check, then `make restart`
# - Missing env var: Run `make env-check`
# - Port conflict: Change PORT in .env
# - Default secrets in prod: App crashes intentionally - change them!
```

### Database issues

```bash
# Check current migration
make db-current

# Reset database (WARNING: deletes all data)
make db-reset

# Open psql for manual debugging
make psql
```

### WhatsApp not receiving messages

1. Check webhook is registered: Meta Developer Console > Webhooks
2. Check signature: `make app-logs` and look for signature warnings
3. Check token: Visit health dashboard (`make health`)
4. Check rate limits: `make redis-cli` then `KEYS *rate*`

### Health dashboard shows "down"

```bash
# Check individual services
make db-logs     # PostgreSQL
make redis-logs  # Redis

# Check health JSON for details
make health-json
```

---

## Branching Strategy

| Branch | Purpose |
|---|---|
| `main` | Production-ready code |
| `develop` | Active development |
| `feature/*` | New features |
| `fix/*` | Bug fixes |

## Pull Request Checklist

- [ ] App starts with `make up`
- [ ] No startup exceptions in `make app-logs`
- [ ] `make compile-check` passes
- [ ] `make lint` passes
- [ ] All new i18n keys have all 6 languages
- [ ] Database migration generated if models changed
- [ ] No secrets committed (check `git diff --cached`)
