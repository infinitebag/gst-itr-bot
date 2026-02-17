# GST + ITR WhatsApp Bot

A **production-ready WhatsApp bot** for Indian tax compliance — GST return filing,
ITR computation, invoice OCR, AI-powered tax insights, and a Chartered Accountant (CA)
dashboard. Built with FastAPI, PostgreSQL, Redis, and OpenAI GPT-4o.

> **Complete beginner?** Follow this guide top to bottom. You'll have the bot running
> in under 15 minutes using Docker — no Python installation needed on your machine.

---

## Table of Contents

1. [What This Bot Does](#what-this-bot-does)
2. [Architecture Overview](#architecture-overview)
3. [Tech Stack](#tech-stack)
4. [Prerequisites](#prerequisites)
5. [Project Structure](#project-structure)
6. [Quick Start — Docker (Recommended)](#quick-start--docker-recommended)
7. [Quick Start — Local Development](#quick-start--local-development)
8. [Environment Variables Explained](#environment-variables-explained)
9. [Connecting WhatsApp (Meta Cloud API)](#connecting-whatsapp-meta-cloud-api)
10. [Verifying Everything Works](#verifying-everything-works)
11. [Daily Development Workflow](#daily-development-workflow)
12. [Makefile Commands Reference](#makefile-commands-reference)
13. [Database Management](#database-management)
14. [Admin & CA Dashboards](#admin--ca-dashboards)
15. [How the Bot Works (State Machine)](#how-the-bot-works-state-machine)
16. [Supported Languages](#supported-languages)
17. [Common Errors & Fixes](#common-errors--fixes)
18. [Production Deployment Checklist](#production-deployment-checklist)
19. [Contributing](#contributing)
20. [License](#license)

---

## What This Bot Does

Users interact via **WhatsApp** to:

| Category | Features |
|---|---|
| **GST** | GSTIN validation, invoice upload (OCR + AI parsing), batch invoices, GSTR-1/3B prep, NIL filing, HSN code lookup, invoice PDF export |
| **e-Invoice** | Step-by-step IRN generation, status checking, cancellation via WhatsApp conversational flow |
| **e-WayBill** | Generate, track, update vehicle details for e-WayBills via WhatsApp |
| **GST Wizard** | Guided wizard for small-segment users: upload sales → purchases → auto-summary → CA review |
| **Credit Check** | GSTR-2B auto-import, invoice reconciliation, missing bill detection for medium-segment users |
| **Multi-GSTIN** | Manage multiple GSTINs per user — add, switch, label, consolidated summary view |
| **Refund & Notices** | Refund claim tracking (excess balance, export, inverted duty), GST notice management, export services |
| **ITR** | ITR-1 (salary) and ITR-4 (presumptive) computation via conversational flow, Old vs New regime comparison, 80C/80D/80E deductions |
| **AI Insights** | Tax summary, anomaly detection, AI-powered insights (GPT-4o), filing deadline tracking, conversational tax Q&A |
| **Notifications** | Proactive filing deadline reminders, risk alerts, notification preferences (filing reminders, status updates) |
| **Segment Gating** | 3 user segments (small/medium/enterprise) with dynamic feature menus and WhatsApp interactive messages |
| **CA Portal** | JWT-protected dashboard for Chartered Accountants to manage clients and filing status |
| **Admin** | System health dashboard, dead letter management, usage stats, invoice CRUD |
| **Security & Compliance** | PII masking (GSTIN, PAN, phone, bank accounts), upload malware scanning, file validation, audit trail for data access |

---

## Architecture Overview

```
WhatsApp User
      │
      ▼
Meta Cloud API  ──webhook──▶  Cloudflare (api.mytaxpe.com)
                                    │
                              Cloudflare Tunnel
                                    │
                                    ▼
                              FastAPI App (port 8000)
                                    │
                         ┌──────────┼──────────┐
                         ▼          ▼          ▼
                    PostgreSQL    Redis     OpenAI GPT-4o
                    (pgvector,   (sessions, (intent detection,
                     users,       rate       invoice parsing,
                     invoices,    limits,    tax Q&A, RAG,
                     audit logs)  queues)    insights)
                         ▲
                         │
                    RQ Worker
                    (background jobs)
```

**Key design principles:**
- **Layered architecture**: API → Domain → Infrastructure → Core
- **State machine**: 50+ WhatsApp conversation states with stack-based navigation and modular handler chain
- **Background workers**: Rate-limited message sender + deadline reminder loop
- **Security**: HMAC webhook verification, timing-safe auth, startup secret validation
- **Security**: PII masking in all logs, upload malware scanning, audit trail for client data access

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Web Framework | FastAPI (async) | API endpoints, webhook handler |
| Database | PostgreSQL 16 + pgvector | Users, invoices, audit logs, vector embeddings |
| Migrations | Alembic | Schema versioning |
| Cache / Queue | Redis 7 | Session state, rate limiting, job queue |
| AI / NLP | OpenAI GPT-4o | Intent detection, invoice parsing, tax Q&A, RAG |
| ML | scikit-learn + SHAP | Risk scoring, anomaly detection |
| Vector Search | pgvector | RAG knowledge base embeddings |
| OCR | Tesseract | Invoice text extraction |
| PDF | ReportLab | Invoice PDF generation |
| WhatsApp | Meta Cloud API v20.0 | Messaging |
| Voice | Sarvam AI | Speech-to-text for voice messages |
| Translation | Bhashini | Government translation API |
| Auth | JWT + bcrypt | CA dashboard auth |
| Container | Docker + Docker Compose | One-command deployment |
| Language | Python 3.10+ | Everything |

---

## Prerequisites

### What You Need Installed

| Tool | macOS | Ubuntu/Debian | Windows |
|---|---|---|---|
| **Docker Desktop** | [Download](https://www.docker.com/products/docker-desktop) | `sudo apt install docker.io docker-compose-plugin` | [Download](https://www.docker.com/products/docker-desktop) (enable WSL2) |
| **Git** | `brew install git` | `sudo apt install git` | [Download](https://git-scm.com/download/win) |
| **Make** | Pre-installed | `sudo apt install make` | Use Git Bash or WSL |
| **cloudflared** (for WhatsApp) | `brew install cloudflared` | [Download](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) | [Download](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) |

### Verify Your Setup

Open a terminal and run:

```bash
docker --version          # Docker Engine 24+ recommended
docker compose version    # Docker Compose v2+
git --version             # Any recent version
make --version            # GNU Make 3.8+
```

All four commands should print version numbers without errors.

### API Keys You'll Need

| Key | Where to Get It | Required? |
|---|---|---|
| **WhatsApp Access Token** | [Meta Developer Console](https://developers.facebook.com) → Your App → WhatsApp → API Setup | Yes (for WhatsApp) |
| **WhatsApp Phone Number ID** | Same page as above | Yes (for WhatsApp) |
| **WhatsApp App Secret** | Meta Developer Console → Your App → Settings → Basic | Yes (for webhook security) |
| **OpenAI API Key** | [OpenAI Platform](https://platform.openai.com/api-keys) | Yes (for AI features) |
| **ngrok Auth Token** | [ngrok Dashboard](https://dashboard.ngrok.com/get-started/your-authtoken) | Optional (for local WhatsApp testing) |
| **Sarvam API Key** | [Sarvam AI](https://www.sarvam.ai/) | Optional (voice messages) |

> **Don't have API keys yet?** You can still run the bot! It will start fine without
> WhatsApp/OpenAI keys — the health dashboard and admin panel will work. WhatsApp
> messaging and AI features will be disabled until you add the keys.

---

## Project Structure

```
gst_itr_bot/
├── app/
│   ├── main.py                          # FastAPI app entry point
│   ├── core/
│   │   ├── config.py                    # All settings + secret validation
│   │   └── db.py                        # Database engine + sessions
│   ├── db/
│   │   └── base.py                      # SQLAlchemy DeclarativeBase
│   ├── api/
│   │   ├── deps.py                      # Shared auth dependencies
│   │   └── routes/
│   │       ├── whatsapp.py              # Main webhook + state machine
│   │       ├── health.py                # /health endpoint
│   │       ├── system_health.py         # Health dashboard
│   │       ├── admin_dashboard.py       # Admin UI (usage, dead letters)
│   │       ├── admin_whatsapp.py        # WhatsApp admin API
│   │       ├── admin_analytics.py       # AI insights API
│   │       ├── admin_invoices.py        # Invoice CRUD API
│   │       ├── admin_invoice_pdf.py     # Invoice PDF download
│   │       ├── admin_ca_dashboard.py    # CA client overview
│   │       ├── admin_ca_management.py   # CA management API
│   │       ├── admin_auth.py            # Admin authentication
│   │       ├── admin_ml_risk.py         # ML risk scoring API
│   │       ├── admin_segments.py        # Segment management API
│   │       ├── ca_auth.py              # CA login/register (JWT)
│   │       ├── ca_dashboard.py         # CA portal
│   │       ├── ca_gst_review.py        # CA GST review
│   │       ├── ca_itr_review.py        # CA ITR review
│   │       ├── gst_mastergst.py        # MasterGST integration
│   │       ├── gst_periods.py          # GST period management
│   │       ├── gst_annual.py           # GST annual returns (GSTR-9)
│   │       ├── itr_api.py              # ITR REST API
│   │       ├── whatsapp_health.py      # WhatsApp token validation
│   │       ├── gst_debug.py            # GST sandbox debug (dev only)
│   │       ├── gst_gstr1_debug.py      # GSTR-1 debug (dev only)
│   │       └── wa_handlers/            # Modular WhatsApp handler chain
│   │           ├── __init__.py         # Handler chain registry
│   │           ├── einvoice.py         # e-Invoice flow (Phase 6)
│   │           ├── ewaybill.py         # e-WayBill flow (Phase 6)
│   │           ├── gst_wizard.py       # Small-segment wizard (Phase 7)
│   │           ├── gst_credit_check.py # Credit check flow (Phase 7)
│   │           ├── multi_gstin.py      # Multi-GSTIN management (Phase 8)
│   │           ├── refund_notice.py    # Refund + notice flows (Phase 9)
│   │           └── notification_settings.py  # Notification prefs (Phase 10)
│   ├── domain/
│   │   ├── i18n.py                      # Translations (6 languages)
│   │   └── services/
│   │       ├── conversation_service.py  # Chat helpers
│   │       ├── gst_service.py           # GSTR-3B/1 + NIL filing
│   │       ├── itr_service.py           # ITR-1/4 computation
│   │       ├── tax_analytics.py         # Insights + anomalies
│   │       ├── invoice_parser.py        # OCR + LLM parsing
│   │       ├── invoice_pdf.py           # PDF generation
│   │       ├── intent_router.py         # NLP intent routing
│   │       ├── voice_handler.py         # Voice → text
│   │       ├── health_check.py          # System probes
│   │       ├── deadline_scheduler.py    # Reminder cron
│   │       ├── einvoice_flow.py         # e-Invoice IRN service (Phase 6)
│   │       ├── ewaybill_flow.py         # e-WayBill service (Phase 6)
│   │       ├── gst_explainer.py         # Simple language tax explainer (Phase 7)
│   │       ├── multi_gstin_service.py   # Multi-GSTIN management (Phase 8)
│   │       ├── refund_service.py        # Refund claim tracking (Phase 9)
│   │       ├── notice_service.py        # GST notice management (Phase 9)
│   │       ├── notification_service.py  # Proactive notifications (Phase 10)
│   │       ├── pii_masking.py              # PII masking for logs & replies
│   │       ├── upload_security.py          # File validation + malware scanning
│   │       ├── pending_itc_service.py      # Pending ITC tracking + vendor follow-up
│   │       ├── books_vs_portal.py          # Books vs GST portal comparison
│   │       ├── audit_service.py            # Client data access audit trail
│   │       ├── ml_risk_model.py            # ML risk scoring (RandomForest + SHAP)
│   │       ├── segment_detection.py        # User segment detection
│   │       ├── feature_registry.py         # Segment-gated feature registry
│   │       ├── rag_tax_qa.py               # RAG-based tax Q&A (pgvector)
│   │       └── ca_auth.py                  # CA authentication service
│   ├── api/v1/                            # REST API v1 (mobile / web clients)
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
│   ├── infrastructure/
│   │   ├── cache/session_cache.py       # Redis sessions
│   │   ├── db/models.py                # ORM models
│   │   ├── external/
│   │   │   ├── whatsapp_client.py       # Rate-limited sender
│   │   │   ├── whatsapp_media.py        # Media upload/download
│   │   │   └── openai_client.py         # OpenAI integration
│   │   └── ocr/                         # OCR backends
│   ├── static/admin.css                 # Admin styles
│   └── templates/admin/                 # Admin HTML templates
├── migrations/                          # Alembic migrations
├── tests/                               # Test suite
├── Dockerfile                           # App container definition
├── docker-compose.yml                   # All services orchestration
├── Makefile                             # 30+ automation targets
├── requirements-base.txt                # Production dependencies
├── requirements-dev.txt                 # Dev + test dependencies
├── .env.example                         # Environment variable template
├── CONTRIBUTING.md                      # Developer guide (architecture deep dive)
└── README.md                            # ← You are here
```

---

## Quick Start — Docker (Recommended)

This is the fastest way to get running. **No Python installation needed.**

### Step 1: Clone the Repository

```bash
git clone https://github.com/infinitebag/gst-itr-bot.git
cd gst-itr-bot
```

### Step 2: One-Command Setup

```bash
make first-run
```

This single command will:
1. Create `.env.docker` from `.env.example` (if it doesn't exist)
2. Build all Docker images (app, worker)
3. Start PostgreSQL, Redis, app, and worker containers
4. Wait for database health checks
5. Run Alembic database migrations
6. Print all service URLs

**Expected output:**

```
═══════════════════════════════════════════
 Step 1/3: Building containers...
═══════════════════════════════════════════
 ...
═══════════════════════════════════════════
 Step 3/3: Running database migrations...
═══════════════════════════════════════════
 ...
╔════════════════════════════════════════════════════════════╗
║  ✅ First-run complete!                                    ║
║                                                            ║
║  App:     http://localhost:8000                            ║
║  Health:  http://localhost:8000/admin/system-health        ║
║  Admin:   http://localhost:8000/admin/ui/usage             ║
║  CA:      http://localhost:8000/ca/auth/login              ║
╚════════════════════════════════════════════════════════════╝
```

### Step 3: Add Your API Keys

```bash
# Open the environment file in your editor
nano .env.docker     # or: vim .env.docker / code .env.docker
```

Fill in these critical values (see [Environment Variables Explained](#environment-variables-explained)):

```env
# These use Docker internal hostnames — DO NOT change to localhost
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/gst_itr_db
REDIS_URL=redis://redis:6379/0

# Your WhatsApp keys (from Meta Developer Console)
WHATSAPP_VERIFY_TOKEN=your_custom_verify_token
WHATSAPP_ACCESS_TOKEN=your_meta_access_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id
WHATSAPP_APP_SECRET=your_app_secret

# Your OpenAI key
OPENAI_API_KEY=sk-your-openai-key

# Change ALL of these from defaults before going to production!
# Generate each with: openssl rand -hex 32
ADMIN_API_KEY=a_strong_random_string
CA_JWT_SECRET=another_strong_random_string
ADMIN_JWT_SECRET=another_strong_random_string
USER_JWT_SECRET=another_strong_random_string
```

### Step 3b: Validate Your Configuration

```bash
make env-check
```

This checks all 10 required variables and flags any that are missing or still
using unsafe defaults. Fix any ⚠️ warnings before proceeding.

### Step 4: Restart with New Keys

```bash
make restart
```

### Step 5: Expose Webhook (for WhatsApp)

WhatsApp needs a public HTTPS URL to send messages to your bot.

**Option A: Cloudflare Tunnel (Recommended for production)**

If you have a domain and Cloudflare account, set up a named tunnel:

```bash
# Install cloudflared (one-time)
brew install cloudflared        # macOS
# See https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ for other OSes

# Authenticate with Cloudflare
cloudflared tunnel login

# Create a named tunnel
cloudflared tunnel create gst-itr-bot

# Route DNS (replace with your domain)
cloudflared tunnel route dns gst-itr-bot api.yourdomain.com

# Create config file (~/.cloudflared/config.yml)
cat > ~/.cloudflared/config.yml <<EOF
tunnel: <YOUR_TUNNEL_ID>
credentials-file: ~/.cloudflared/<YOUR_TUNNEL_ID>.json
loglevel: warn

ingress:
  - hostname: api.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
EOF

# Start the tunnel
make tunnel
```

Your webhook URL will be `https://api.yourdomain.com/webhook`.

> **Tip:** Install as a system service for auto-start on boot:
> `sudo cloudflared service install`

**Option B: ngrok (Quick local development)**

```bash
make tunnel-ngrok
```

This starts ngrok and shows you a URL like `https://abc123.ngrok-free.app`.
Copy this URL — you'll need it for [Connecting WhatsApp](#connecting-whatsapp-meta-cloud-api).

> **Note:** ngrok free-tier URLs change every restart. For persistent webhooks,
> use Cloudflare Tunnel (Option A) or an ngrok paid plan.

### Step 6: Verify

```bash
# Check all containers are running
make ps

# Check app health
make health-json

# Open health dashboard in browser
make health
```

---

## Quick Start — Local Development

Use this if you prefer running Python directly on your machine (useful for debugging
with breakpoints, IDE integration, etc.).

### Step 1: Clone and Create Virtual Environment

```bash
git clone https://github.com/infinitebag/gst-itr-bot.git
cd gst-itr-bot

# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### Step 2: Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements-dev.txt
```

### Step 3: Install Tesseract OCR

Tesseract is needed for invoice text extraction.

```bash
# macOS
brew install tesseract

# Ubuntu / Debian
sudo apt install tesseract-ocr libtesseract-dev

# Windows (with Chocolatey)
choco install tesseract

# Verify
tesseract --version
```

### Step 4: Start PostgreSQL and Redis via Docker

Even in local dev, we use Docker for databases (simplest approach):

```bash
# Start PostgreSQL
docker run -d \
  --name gst-postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=gst_itr_db \
  -p 5432:5432 \
  postgres:16-alpine

# Start Redis
docker run -d \
  --name gst-redis \
  -p 6379:6379 \
  redis:7-alpine

# Verify both are running
docker ps
```

### Step 5: Configure Environment

```bash
cp .env.example .env.local
```

Edit `.env.local` with your editor. Key differences from Docker:

```env
# LOCAL uses localhost (not Docker service names)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/gst_itr_db
REDIS_URL=redis://localhost:6379/0

# Fill in your API keys
WHATSAPP_VERIFY_TOKEN=your_verify_token
WHATSAPP_ACCESS_TOKEN=your_meta_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_id
OPENAI_API_KEY=sk-your-key
```

> **Important:** Local dev uses `localhost` for DB and Redis. Docker uses `db` and
> `redis` (Docker service names). Don't mix them up!

### Step 6: Run Database Migrations

```bash
alembic upgrade head
```

### Step 7: Start the App

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The `--reload` flag auto-restarts the server when you change code.

### Step 8: Start the Background Worker (separate terminal)

```bash
source venv/bin/activate

# ARQ worker (handles WhatsApp sending, embedding jobs, ML retrain)
arq app.infrastructure.queue.arq_settings.WorkerSettings

# Or the legacy RQ worker (basic task queue)
# rq worker default --url redis://localhost:6379/0
```

### Step 9: Verify

Open in your browser:
- App health: http://localhost:8000/health
- Health dashboard: http://localhost:8000/admin/system-health
- Admin panel: http://localhost:8000/admin/ui/usage

---

## Environment Variables Explained

All environment variables are documented in `.env.example`. Here's a beginner-friendly
breakdown:

### Core (Required)

| Variable | What It Is | Example Value |
|---|---|---|
| `ENV` | Environment mode | `dev` (local) or `production` |
| `PORT` | App port | `8000` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql+asyncpg://postgres:postgres@db:5432/gst_itr_db` |
| `REDIS_URL` | Redis connection | `redis://redis:6379/0` |

### WhatsApp (Required for messaging)

| Variable | What It Is | Where to Find It |
|---|---|---|
| `WHATSAPP_VERIFY_TOKEN` | A string YOU choose | You define this — use any random string |
| `WHATSAPP_ACCESS_TOKEN` | Meta API token | Meta Developer Console → WhatsApp → API Setup |
| `WHATSAPP_PHONE_NUMBER_ID` | Your WhatsApp number ID | Same page as above |
| `WHATSAPP_APP_SECRET` | App secret for signature verification | Meta Developer Console → Settings → Basic |

### AI (Required for smart features)

| Variable | What It Is | Where to Find It |
|---|---|---|
| `OPENAI_API_KEY` | OpenAI API key | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `OPENAI_MODEL` | Model to use (default: `gpt-4o`) | Optional — leave default |
| `OPENAI_TIMEOUT` | API timeout in seconds | Optional — default 30 |

### Security (Change before production!)

| Variable | Default | What to Change It To |
|---|---|---|
| `ADMIN_API_KEY` | `dev_admin_key` | `openssl rand -hex 32` |
| `CA_JWT_SECRET` | `change-me-in-production` | `openssl rand -hex 32` |
| `ADMIN_JWT_SECRET` | `change-me-admin-jwt` | `openssl rand -hex 32` |
| `USER_JWT_SECRET` | `change-me-user-jwt` | `openssl rand -hex 32` |

> **The app will CRASH on startup** if you deploy to production with default secrets.
> This is intentional — it prevents accidental insecure deployments.

### RAG / Knowledge Base

| Variable | Default | What It Does |
|---|---|---|
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model for vector search |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions |
| `RAG_TOP_K` | `5` | Number of retrieval results |
| `RAG_SIMILARITY_THRESHOLD` | `0.7` | Minimum similarity score |
| `RAG_CHUNK_SIZE` | `500` | Tokens per document chunk |
| `RAG_CHUNK_OVERLAP` | `50` | Overlap between chunks |

### ML Risk Scoring

| Variable | Default | What It Does |
|---|---|---|
| `ML_RISK_ENABLED` | `true` | Enable ML-based risk assessment |
| `ML_RISK_BLEND_WEIGHT` | `0.3` | Blend weight (0=rules only, 1=ML only) |
| `ML_RISK_MIN_SAMPLES` | `50` | Cold-start threshold before ML kicks in |
| `ML_RISK_SHAP_ENABLED` | `true` | Enable SHAP explainability |

### Segment Gating

| Variable | Default | What It Does |
|---|---|---|
| `SEGMENT_GATING_ENABLED` | `true` | Enable segment-based feature menus |
| `DEFAULT_SEGMENT` | `small` | Default: `small`, `medium`, or `enterprise` |
| `SEGMENT_CACHE_TTL` | `3600` | Segment cache TTL in seconds |

### Notifications

| Variable | Default | What It Does |
|---|---|---|
| `NOTIFICATION_ENABLED` | `true` | Enable proactive deadline reminders |
| `NOTIFICATION_CHECK_INTERVAL_SECONDS` | `3600` | Check interval (1 hour) |
| `NOTIFICATION_REMINDER_DAYS` | `[7, 3, 1]` | Days before deadline to remind |

### OTP / Email (Optional)

| Variable | Default | What It Does |
|---|---|---|
| `OTP_EMAIL_ENABLED` | `false` | Enable email-based OTP verification |
| `OTP_SMTP_HOST` | _(empty)_ | SMTP server (e.g. `smtp.gmail.com`) |
| `OTP_SMTP_PORT` | `587` | SMTP port |
| `OTP_FROM_EMAIL` | `noreply@example.com` | Sender email address |

### Optional Services

| Variable | Purpose |
|---|---|
| `SARVAM_API_KEY` | Voice message transcription (Sarvam STT) |
| `BHASHINI_USER_ID` / `BHASHINI_ULCA_API_KEY` | Government translation API |
| `MASTERGST_*` | MasterGST sandbox/production integration |
| `OCR_BACKEND` | `tesseract` (default) or `google_vision` |

---

## Connecting WhatsApp (Meta Cloud API)

This section walks you through connecting the bot to WhatsApp.

### Step 1: Create a Meta Developer App

1. Go to [developers.facebook.com](https://developers.facebook.com)
2. Click **"My Apps"** → **"Create App"**
3. Choose **"Business"** type
4. Add the **"WhatsApp"** product to your app

### Step 2: Get Your Credentials

In Meta Developer Console:
1. Go to **WhatsApp** → **API Setup**
2. Note your **Phone Number ID** and **Temporary Access Token**
3. Go to **App Settings** → **Basic** → note your **App Secret**

Put these in your `.env.docker` (or `.env.local`):

```env
WHATSAPP_ACCESS_TOKEN=your_temporary_token
WHATSAPP_PHONE_NUMBER_ID=your_phone_id
WHATSAPP_APP_SECRET=your_app_secret
```

### Step 3: Set Up the Webhook

1. Start your bot and expose it to the internet:
   ```bash
   make up          # Start the bot
   make tunnel      # Start Cloudflare Tunnel (or: make tunnel-ngrok)
   ```

2. In Meta Developer Console → **WhatsApp** → **Configuration**:
   - **Callback URL**: `https://your-domain.com/webhook` (your tunnel URL + `/webhook`)
   - **Verify Token**: The same value as `WHATSAPP_VERIFY_TOKEN` in your `.env`

3. Click **"Verify and Save"**

4. Subscribe to webhook fields:
   - ✅ `messages`
   - ✅ `messaging_postbacks`

### Step 4: Send a Test Message

1. In Meta Developer Console → **WhatsApp** → **API Setup**
2. Add your phone number as a test recipient
3. Send a WhatsApp message to the test number
4. Check `make app-logs` to see the bot processing your message

> **Tip:** The temporary access token expires after 24 hours. For persistent access,
> create a **System User** and generate a **permanent token** in Meta Business Settings.

---

## Verifying Everything Works

After setup, run these checks:

### Quick Health Check

```bash
# JSON health status
make health-json
```

Expected output:
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "whatsapp_token": "valid",
  "uptime_seconds": 120
}
```

### Visual Health Dashboard

```bash
make health
```

Opens http://localhost:8000/admin/system-health in your browser — a live dashboard
showing database, Redis, WhatsApp, and OpenAI status with auto-refresh.

### Validate Environment Variables

```bash
make env-check
```

This checks all 10 required variables and flags any that are missing or still using
unsafe defaults.

### Create a Test CA User

```bash
make seed-ca
```

Creates a test Chartered Accountant user:
- **Email:** `admin@example.com`
- **Password:** `admin123`
- **Login URL:** http://localhost:8000/ca/auth/login

---

## Daily Development Workflow

### After Changing Code

```bash
# Docker auto-reloads on code changes (--reload is enabled)
# But if you changed dependencies or Dockerfile:
make build && make restart
```

### After Changing Database Models

```bash
# Generate a new migration
make db-revision MSG='describe your model change'

# Apply the migration
make db-upgrade

# Verify
make db-current
```

### Checking Logs

```bash
make app-logs        # App container logs (most useful)
make worker-logs     # Background worker logs
make logs            # ALL container logs
```

### Running Code Quality Checks

```bash
make lint            # Check for code issues
make fmt             # Auto-format code
make compile-check   # Verify all Python files compile
make test            # Run test suite
```

---

## Makefile Commands Reference

Run `make help` to see all commands. Here's the complete list:

### Quick Start
| Command | Description |
|---|---|
| `make first-run` | Full first-time setup (build → migrate → start) |
| `make setup` | Copy `.env.example` → `.env.docker` |

### Docker Lifecycle
| Command | Description |
|---|---|
| `make up` | Build + start all services |
| `make up-deps` | Start only PostgreSQL + Redis |
| `make up-app` | Start only app + worker |
| `make build` | Incremental build (uses cache) |
| `make rebuild` | Full rebuild (no cache) |
| `make restart` | Restart app + worker |
| `make down` | Stop all containers |
| `make clean` | Stop + DELETE all data (asks for confirmation) |

### Status & Logs
| Command | Description |
|---|---|
| `make ps` | Show container statuses |
| `make logs` | Follow ALL container logs |
| `make app-logs` | Follow app logs |
| `make worker-logs` | Follow worker logs |
| `make db-logs` | Follow PostgreSQL logs |
| `make redis-logs` | Follow Redis logs |

### Shell Access
| Command | Description |
|---|---|
| `make sh` | Shell into app container |
| `make worker-sh` | Shell into worker container |
| `make psql` | Open PostgreSQL prompt |
| `make redis-cli` | Open Redis CLI |
| `make run CMD='...'` | Run any command in app container |

### Database (Alembic)
| Command | Description |
|---|---|
| `make db-init` | Create initial migration + apply |
| `make db-revision MSG='...'` | Generate new migration |
| `make db-upgrade` | Apply all pending migrations |
| `make db-downgrade REV='...'` | Rollback to a revision |
| `make db-history` | Show migration history |
| `make db-current` | Show current revision |
| `make db-reset` | Drop all tables + re-migrate (asks confirmation) |

### Health & Quality
| Command | Description |
|---|---|
| `make health` | Open health dashboard in browser |
| `make health-json` | Fetch health status as JSON |
| `make lint` | Run ruff linter |
| `make fmt` | Auto-format code |
| `make check` | Lint + format check (CI-friendly) |
| `make compile-check` | Verify all `.py` files compile |
| `make test` | Run pytest |
| `make test-cov` | Run pytest with coverage |

### Utilities
| Command | Description |
|---|---|
| `make tunnel` | Start Cloudflare Tunnel (`api.mytaxpe.com → localhost:8000`) |
| `make tunnel-ngrok` | Start ngrok tunnel (local dev fallback) |
| `make env-check` | Validate required env vars |
| `make seed-ca` | Create test CA user |

---

## Database Management

### How Data is Stored

| Model | Table | Purpose |
|---|---|---|
| `User` | `users` | WhatsApp users (phone number, preferences) |
| `Session` | `sessions` | Conversation state, language, step |
| `Invoice` | `invoices` | Parsed tax invoices (GSTIN, amounts, tax) |
| `WhatsAppMessageLog` | `whatsapp_message_logs` | Message audit trail |
| `WhatsAppDeadLetter` | `whatsapp_dead_letters` | Failed messages for retry |
| `CAUser` | `ca_users` | Chartered Accountant accounts |
| `BusinessClient` | `business_clients` | CA's client roster |
| `Feature` | `features` | Segment-gated feature definitions |
| `SegmentFeature` | `segment_features` | Feature visibility per segment |
| `UserGSTIN` | `user_gstins` | Multi-GSTIN management per user |
| `RefundClaim` | `refund_claims` | GST refund claim tracking |
| `GSTNotice` | `gst_notices` | GST notice management |
| `NotificationSchedule` | `notification_schedules` | Proactive notification scheduling |
| `ReturnPeriod` | `return_periods` | GST return period tracking |
| `Gstr2bInvoice` | `gstr2b_invoices` | GSTR-2B imported invoices |
| `ReconciliationResult` | `reconciliation_results` | Invoice matching results |
| `RiskAssessment` | `risk_assessments` | ML-based risk scoring |

### Common Database Tasks

```bash
# Open a PostgreSQL shell to inspect data
make psql

# Inside psql:
\dt                          -- List all tables
SELECT COUNT(*) FROM users;  -- Count users
SELECT * FROM invoices LIMIT 5;  -- View recent invoices
\q                           -- Exit

# Check migration status
make db-current

# View full migration history
make db-history

# Nuclear option: reset everything (confirmation required)
make db-reset
```

### Where is the Data?

- Data is stored in a **Docker volume** named `pgdata`
- It **survives** container restarts (`make restart`, `make down`)
- It is **deleted** only by `make clean` (which asks for confirmation)

---

## Admin & CA Dashboards

### Admin Dashboard (Token-based)

Access admin pages by adding the `X-Admin-Token` header with your `ADMIN_API_KEY` value.

| Page | URL | Description |
|---|---|---|
| Usage Stats | http://localhost:8000/admin/ui/usage | Message volumes, active users |
| Dead Letters | http://localhost:8000/admin/ui/dead-letters | Failed messages for replay |
| System Health | http://localhost:8000/admin/system-health | Live status dashboard |
| Health JSON | http://localhost:8000/admin/system-health/json | Machine-readable status |

**API access example:**

```bash
# List dead letters
curl -H "X-Admin-Token: your_admin_key" http://localhost:8000/admin/whatsapp/dead-letters

# Get AI insights for a user
curl -H "X-Admin-Token: your_admin_key" http://localhost:8000/admin/analytics/insights/919876543210
```

### CA Portal (JWT-based)

| Page | URL |
|---|---|
| Login | http://localhost:8000/ca/auth/login |
| Dashboard | http://localhost:8000/ca/dashboard/ |

```bash
# Create a test CA user first
make seed-ca

# Login credentials:
# Email: admin@example.com
# Password: admin123
```

---

## How the Bot Works (State Machine)

The bot uses a **state machine** to track each user's position in the conversation.
States are stored in Redis and persist across messages.

```
                    ┌───────────┐
                    │ MAIN_MENU │  ← "0" from any state resets here
                    └─────┬─────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
       ┌─────────┐  ┌─────────┐  ┌──────────┐
       │GST_MENU │  │ITR_MENU │  │  TAX_QA  │
       └────┬────┘  └────┬────┘  └──────────┘
            │             │
   ┌────────┼────────┐   ├──────────┐
   ▼        ▼        ▼   ▼          ▼
GSTIN    FILING    UPLOAD  ITR-1     ITR-4
VALID    MENU      (OCR)  (5 steps) (4 steps)
         │
    ┌────┼────┐──────────────────────────┐
    ▼    ▼    ▼        ▼        ▼        ▼
 GSTR-3B NIL  GSTR-1  e-INV   e-WB    MULTI
  prep  FILE   prep   (6st)   (5st)   GSTIN
                        │              (4 st)
              ┌─────────┼──────────┐
              ▼         ▼          ▼
           WIZARD    CREDIT     REFUND
           (small)   CHECK      NOTICE
           (3 st)    (medium)   (6 st)
                     (3 st)
```

**Special shortcuts (work from any state):**
- `0` → Reset to Main Menu
- `9` → Go Back (pop navigation stack)
- `NIL` → Jump to NIL filing
- `help` or `?` → Show quick command reference
- `restart` → Clear session and return to Main Menu
- `ca` or `talk to ca` → Request CA handoff

---

## Supported Languages

| Code | Language | Coverage |
|---|---|---|
| `en` | English | Full |
| `hi` | Hindi | Full |
| `gu` | Gujarati | Full |
| `ta` | Tamil | Full |
| `te` | Telugu | Full |
| `kn` | Kannada | Full |

Users select their language from the WhatsApp menu. All bot responses, menus, and
error messages are translated across all 6 languages.

---

## Security & Compliance Features

### PII Masking
All sensitive data is automatically masked in logs and debugging output:
- **GSTIN**: `36AABCU9603R1ZM` → `36**********1ZM`
- **PAN**: `AABCU9603R` → `AA*****03R`
- **Phone**: `+919876543210` → `+91*****3210`
- **Bank Account**: `1234567890` → `******7890`

Use `mask_for_log(text)` from `app.domain.services.pii_masking` for any user-facing logs.

### Upload Security
All file uploads (invoices, notices, documents) are validated before processing:
- File size limits (10 MB images, 25 MB PDFs)
- MIME type allowlist (JPEG, PNG, PDF, Excel, CSV)
- Magic byte verification (detects disguised files)
- PDF malware pattern scanning (JavaScript, Launch, EmbeddedFile)
- Path traversal and null byte protection

### Audit Trail
Client data access is logged for compliance:
- All GSTIN lookups and data views are recorded
- Admin REST API at `/api/v1/audit/recent` and `/api/v1/audit/client/{gstin}`
- In-memory ring buffer (10,000 entries) with structured logging

### Global Commands
These commands work from any conversation state:
| Command | Action |
|---|---|
| `help` or `?` | Show quick command reference |
| `restart` | Clear session, return to Main Menu |
| `ca` or `talk to ca` | Request CA professional handoff |
| `0` | Return to Main Menu |
| `9` | Go back (pop navigation stack) |
| `NIL` | Jump to NIL filing |

### GSTR-2B Multi-Format Import
Purchase data can be imported from multiple formats:
- **JSON**: Direct API import from GST portal
- **Excel**: `.xlsx` files with supplier GSTIN, invoice details, and tax amounts
- **PDF**: Scanned/downloaded GSTR-2B statements parsed via OCR

### Books vs Portal Comparison
Compare your accounting books against GST portal data:
- Sales register vs GSTR-1 filed data
- Purchase register vs GSTR-2B received data
- Tolerance-based matching (₹1 threshold)
- Mismatch categorization: value mismatch, missing in portal, missing in books

### Pending ITC Tracking
Track unmatched Input Tax Credit across filing periods:
- Identify invoices missing from GSTR-2B
- Age-based bucketing (1 period, 2-3 periods, 4+ periods)
- Automated vendor follow-up WhatsApp messages
- Period-to-period carry-forward

---

## Common Errors & Fixes

### ❌ `make first-run` fails with "Cannot connect to Docker daemon"

**Cause:** Docker Desktop is not running.

**Fix:** Start Docker Desktop, wait for it to be ready, then retry.

### ❌ Container `gst_itr_app` keeps restarting

**Cause:** Usually a missing environment variable or database connection issue.

**Fix:**
```bash
make app-logs        # Check what error is printed
make env-check       # Verify all required vars are set
```

### ❌ "RuntimeError: CA_JWT_SECRET is still set to the unsafe default"

**Cause:** You set `ENV=production` but didn't change the default secrets.

**Fix:** Generate proper secrets:
```bash
# Generate a random secret
openssl rand -hex 32

# Put the output in your .env file as CA_JWT_SECRET and ADMIN_API_KEY
```

### ❌ Port 5432 or 8000 already in use

**Cause:** Another service is using the port.

**Fix:**
```bash
# Find what's using the port
lsof -i :5432    # or :8000

# Stop the conflicting service, or change PORT in .env
```

### ❌ `no such service: postgres`

**Cause:** The PostgreSQL service is named `db` (not `postgres`) in docker-compose.yml.

**Fix:** Use `make psql` instead of `docker compose exec postgres psql`.

### ❌ Redis connection error

**Fix:**
```bash
make ps              # Check if redis container is running
make up-deps         # Start db + redis if they're down
```

### ❌ WhatsApp messages not arriving

**Fix checklist:**
1. Is your tunnel running? → `make tunnel` (Cloudflare) or `make tunnel-ngrok` (ngrok)
2. Is webhook URL correct in Meta Console? → Should be `https://your-domain.com/webhook`
3. Is verify token matching? → Check `WHATSAPP_VERIFY_TOKEN` in `.env`
4. Is app secret set? → Check `WHATSAPP_APP_SECRET` in `.env` (needed for signature verification)
5. Check app logs → `make app-logs` (look for signature warnings)
6. Check webhook health → `make health-json`

### ❌ Alembic "Target database is not up to date"

**Fix:**
```bash
make db-upgrade      # Apply pending migrations
```

### ❌ "Ellipsis object has no attribute __module__"

**Cause:** A function argument was passed as `...` (Python Ellipsis).

**Fix:** Always pass real functions to `enqueue()`, not `...`.

### 🧹 Nuclear Option (if all else fails)

```bash
# Completely clean slate — DELETES ALL DATA
make clean
make first-run
```

---

## Production Deployment Checklist

Before deploying to production, verify:

- [ ] `ENV=production` is set in your environment file
- [ ] `CA_JWT_SECRET` changed from default (`openssl rand -hex 32`)
- [ ] `ADMIN_API_KEY` changed from default (`openssl rand -hex 32`)
- [ ] `WHATSAPP_APP_SECRET` is set (webhook signature verification)
- [ ] `OPENAI_API_KEY` is set (AI features)
- [ ] `WHATSAPP_ACCESS_TOKEN` is a **permanent** token (not temporary 24h one)
- [ ] Run `make env-check` — all 8 variables should show ✅
- [ ] Database migrations applied (`make db-upgrade`)
- [ ] `ADMIN_JWT_SECRET` changed from default (`openssl rand -hex 32`)
- [ ] `USER_JWT_SECRET` changed from default (`openssl rand -hex 32`)
- [ ] CORS origins updated in `app/main.py` for your domain
- [ ] Webhook URL set to `https://your-domain.com/webhook` in Meta Developer Console
- [ ] Cloudflare Tunnel running (`make tunnel` or `sudo cloudflared service install`)
- [ ] Consider managed PostgreSQL (AWS RDS, Neon, Supabase) instead of Docker
- [ ] Consider managed Redis (AWS ElastiCache, Upstash) instead of Docker

### Production Run

```bash
# Use a production env file
ENV_FILE=.env.production make up

# Start Cloudflare Tunnel (permanent webhook endpoint)
make tunnel

# Or install as system service (auto-starts on boot)
sudo cloudflared service install
```

---

## Contributing

See **[CONTRIBUTING.md](CONTRIBUTING.md)** for the full developer guide, including:

- Architecture deep dive (layer diagram, design patterns)
- Full WhatsApp state machine documentation (all 50+ states)
- How to add new conversational flows
- How to add new admin endpoints
- How to add new database models
- API endpoint reference
- Branching strategy and PR checklist
- i18n guide (adding new languages)

---

## License

This project is private. Contact the repository owner for licensing information.

---

**Built with FastAPI, PostgreSQL, Redis, OpenAI, and Tesseract OCR for Indian tax compliance.**
