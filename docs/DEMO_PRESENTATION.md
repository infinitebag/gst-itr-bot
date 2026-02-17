# GST + ITR WhatsApp Bot — Demo Presentation

---

## Slide 1: Title

### GST + ITR WhatsApp Bot
**AI-Powered Tax Compliance on WhatsApp**

- Automated GST & ITR filing for Indian businesses
- WhatsApp-native conversational interface
- Multilingual support (5 languages)
- Built with FastAPI + OpenAI GPT-4o + MasterGST

---

## Slide 2: The Problem

### Tax Compliance in India is Complex

- **70M+ GST-registered businesses** file returns monthly/quarterly
- **6.5 Cr+ ITR filings** annually — many miss deadlines
- Small businesses rely on CAs for even basic filings
- Manual data entry from paper invoices is error-prone
- Language barrier — most business owners prefer regional languages
- No mobile-first, conversational tax tool exists

### The Cost of Non-Compliance
- Late fees: Rs 50/day (GSTR-3B), Rs 200/day (GSTR-1)
- Interest: 18% p.a. on outstanding tax
- ITR penalty: Up to Rs 10,000 for late filing

---

## Slide 3: The Solution

### WhatsApp-First Tax Assistant

```
User sends invoice photo
        |
    [GPT-4o Vision]
        |
  Structured data extracted
        |
  GSTR-3B auto-prepared
        |
  One-click filing via MasterGST
```

**Why WhatsApp?**
- 500M+ WhatsApp users in India
- No app download required
- Works on any smartphone
- Familiar interface for all age groups

---

## Slide 4: Key Features Overview

| Feature | Description |
|---------|-------------|
| **Invoice OCR** | Upload photo/PDF → AI extracts all fields |
| **GST Filing** | GSTR-3B, GSTR-1, NIL filing via MasterGST |
| **ITR Computation** | ITR-1 (salaried) & ITR-4 (business) with Old vs New regime |
| **Document Parsing** | Form 16, Form 26AS, AIS auto-extraction |
| **Tax Q&A** | Conversational tax advice powered by GPT-4o |
| **HSN Lookup** | Describe product → get HSN code + GST rate |
| **Anomaly Detection** | Duplicate invoices, invalid GSTINs, outlier alerts |
| **Filing Deadlines** | Proactive reminders for GST & ITR due dates |
| **CA Dashboard** | Client management portal for Chartered Accountants |
| **5 Languages** | English, Hindi, Gujarati, Tamil, Telugu |

---

## Slide 5: Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    WhatsApp Cloud API (v20.0)                │
│                  (HMAC-SHA256 verified webhooks)             │
└────────────────────────┬─────────────────────────────────────┘
                         │
              ┌──────────▼──────────┐
              │   FastAPI Gateway   │
              │   (async, uvicorn)  │
              └──────────┬──────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────▼────┐    ┌─────▼─────┐   ┌─────▼──────┐
    │   API   │    │  Domain   │   │   Infra    │
    │ Routes  │    │ Services  │   │   Layer    │
    └────┬────┘    └─────┬─────┘   └─────┬──────┘
         │               │               │
         │    ┌──────────┬┴──────────┐    │
         │    │          │           │    │
         ▼    ▼          ▼           ▼    ▼
    ┌─────┐ ┌─────┐ ┌────────┐ ┌──────┐ ┌──────────┐
    │Redis│ │ DB  │ │OpenAI  │ │Master│ │Tesseract │
    │Cache│ │PgSQL│ │GPT-4o  │ │ GST  │ │  OCR     │
    └─────┘ └─────┘ └────────┘ └──────┘ └──────────┘
```

### Tech Stack
| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + Python 3.12 |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| AI Engine | OpenAI GPT-4o |
| OCR | Tesseract + Google Vision |
| GST Filing | MasterGST Sandbox API |
| PDF | ReportLab |
| Auth | JWT (CA) + HMAC (Webhook) |
| Deploy | Docker Compose (5 containers) |

---

## Slide 6: Menu Navigation

### Main Menu (4 options)
```
Welcome to GST + ITR Bot

Choose an option:
1) GST Services
2) ITR Services
3) Ask Tax Question
4) Settings & Account

Reply 1-4 or type your question!

At any time:
0 = Main Menu
9 = Back
```

### Navigation Design Principles
- **Max 5 options per screen** (WhatsApp best practice)
- **Stack-based back navigation** (press 9 anytime)
- **Global shortcuts** (0 = home, NIL = quick file)
- **NLP fallback** — type naturally instead of numbers
- **Voice support** — speak your request

---

## Slide 7: GST Services Flow

### GST Menu
```
GST Services

1) Enter GSTIN
2) GST Filing (GSTR-3B/1)
3) HSN Code Lookup
4) NIL GST Return (One-Click)
5) Upload & Scan Invoices

Reply 1-5
```

### Invoice Upload & Parsing
```
User: [sends invoice photo]

Bot: Processing your invoice... please wait.

Bot: --- Invoice Parsed ---

     Supplier: ABC Traders
     Supplier GSTIN: 27AABCU9603R1ZP ✓
     Buyer GSTIN: 29AALCB1234C1Z5 ✓

     Invoice No: INV-2024-0142
     Date: 15-Jan-2025

     Taxable Value: ₹50,000.00
       CGST: ₹4,500.00
       SGST: ₹4,500.00
       GST Rate: 18%
     Tax Amount: ₹9,000.00
     *Total: ₹59,000.00*
```

### Parsing Strategy (3-tier fallback)
1. **GPT-4o Vision** — direct image understanding
2. **Tesseract OCR + LLM** — text extraction + AI parsing
3. **OCR + Regex** — pattern matching fallback

---

## Slide 8: GST Filing Demo

### GSTR-3B Auto-Preparation
```
--- GSTR-3B Summary ---

Outward Taxable Supplies:
  Taxable Value: Rs 5,00,000
  IGST: Rs 0
  CGST: Rs 45,000
  SGST: Rs 45,000

ITC Eligible:
  IGST: Rs 0
  CGST: Rs 12,000
  SGST: Rs 12,000

Net Tax Payable:
  CGST: Rs 33,000
  SGST: Rs 33,000
  TOTAL: Rs 66,000
```

### NIL Filing (One-Click)
```
User: NIL

Bot: NIL GST Return

     GSTIN: 27AABCU9603R1ZP
     Period: Jan-2025

     1) File GSTR-3B (NIL)
     2) File GSTR-1 (NIL)
     3) File Both

User: 3

Bot: Confirm filing NIL GSTR-3B + GSTR-1
     for Jan-2025? Type YES to proceed.

User: YES

Bot: ✅ NIL return filed successfully via MasterGST!
```

---

## Slide 9: ITR Services Flow

### ITR Computation (ITR-1 / ITR-4)
```
ITR Services

1) Compute ITR-1 (Salaried)
2) Compute ITR-4 (Business/Professional)
3) Upload Documents (Form 16/26AS/AIS)
4) Check Filing Deadlines
```

### ITR-1 Flow (5 questions)
```
Bot: Enter your annual Gross Salary:
User: 1200000

Bot: Enter other income (interest, rent, etc.) or 0:
User: 50000

Bot: Enter Section 80C investments (max 1,50,000):
User: 150000

Bot: Enter Section 80D (health insurance) or 0:
User: 25000

Bot: Enter total TDS deducted:
User: 95000
```

### Tax Result with Regime Comparison
```
━━━ ITR-1 Tax Computation ━━━

         OLD REGIME    NEW REGIME
Income:  ₹12,50,000   ₹12,50,000
Deduct:  ₹2,25,000    ₹75,000
Taxable: ₹10,25,000   ₹11,75,000
Tax:     ₹1,17,000    ₹93,600
Cess:    ₹4,680       ₹3,744
Total:   ₹1,21,680    ₹97,344
TDS:     ₹95,000      ₹95,000
Payable: ₹26,680      ₹2,344

✅ RECOMMENDED: New Regime (Save ₹24,336)

Options:
4) Download PDF
5) Download JSON
```

---

## Slide 10: Document Upload (Form 16 / 26AS / AIS)

### Smart Document Processing
```
User: [uploads Form 16 PDF]

Bot: Processing Form 16... please wait.

Bot: ━━━ Extracted Data Review ━━━

     Source: Form 16
     PAN: ABCPD1234E
     Employer: Tech Corp Ltd

     Gross Salary: ₹15,00,000
     Standard Deduction: ₹75,000
     HRA Exemption: ₹2,40,000
     Section 80C: ₹1,50,000
     Section 80D: ₹25,000
     TDS Deducted: ₹1,20,000

     1) Upload another document
     2) Edit a field
     3) Compute ITR from this data
```

### Multi-Document Merge
- Upload Form 16 → salary data extracted
- Upload 26AS → TDS verified & cross-checked
- Upload AIS → additional income sources merged
- All data combined → auto-compute ITR with pre-filled values

---

## Slide 11: AI-Powered Features

### Tax Q&A (Conversational)
```
User: What is the due date for filing ITR for FY 2024-25?

Bot: The due date for filing ITR for FY 2024-25
     (AY 2025-26) depends on the category:

     - Salaried / Non-audit: 31st July 2025
     - Tax audit cases: 31st October 2025
     - Transfer pricing: 30th November 2025

     Missing the deadline attracts a late fee
     of Rs 5,000 (income > Rs 5 lakh) or
     Rs 1,000 (income ≤ Rs 5 lakh) u/s 234F.
```

### HSN Code Lookup
```
User: I sell cotton t-shirts

Bot: HSN/SAC Code: 6109
     Description: T-shirts, singlets and vests, knitted
     GST Rate: 12%
     Category: Textiles - Apparel
     Chapter: 61 - Knitted/Crocheted Apparel
```

### Invoice Anomaly Detection
```
Tax Anomaly Report

Duplicate invoices: 2
Invalid GSTINs: 1
High-value outliers: 3
Unusual tax rates: 1
Missing fields: 4

Total anomalies: 11
```

---

## Slide 12: Multilingual Support

### 5 Indian Languages

| | English | Hindi | Gujarati | Tamil | Telugu |
|---|---------|-------|----------|-------|--------|
| Menu | ✅ | ✅ | ✅ | ✅ | ✅ |
| Errors | ✅ | ✅ | ✅ | ✅ | ✅ |
| Results | ✅ | ✅ | ✅ | ✅ | ✅ |
| Voice | ✅ | ✅ | ✅ | ✅ | ✅ |

### Switch anytime from Settings
```
भाषा चुनें / Select Language:
1) English
2) हिंदी
3) ગુજરાતી
4) தமிழ்
5) తెలుగు
```

### Voice Message Support
```
User: [sends voice message in Hindi]

Bot: 🎤 आपने कहा: "मेरा GST रिटर्न फाइल करना है"

Bot: GST सेवाएँ

     1) GSTIN दर्ज करें
     2) GST फाइलिंग (GSTR-3B/1)
     ...
```

---

## Slide 13: CA Dashboard

### Chartered Accountant Portal
- **JWT-secured login** with token refresh
- **Client management** — add, edit, track clients
- **Multi-GSTIN support** — manage multiple businesses per client
- **Filing tracker** — see which clients have filed / pending

### Client Management
| Field | Details |
|-------|---------|
| Name | Business name |
| GSTIN | GST Identification Number |
| PAN | Permanent Account Number |
| WhatsApp | Client's number |
| Business Type | Sole Prop / Partnership / Pvt Ltd / LLP |
| Status | Active / Inactive / Suspended |
| Filing Status | Filed / Pending / Overdue |

### REST API Available
```
POST /ca/auth/login       → JWT token
GET  /ca/dashboard        → overview + stats
POST /ca/dashboard/clients → add client
GET  /ca/dashboard/clients/{id} → details
```

---

## Slide 14: Admin Dashboard

### System Health Monitoring
```json
{
  "status": "healthy",
  "database": "connected (PostgreSQL 16)",
  "redis": "connected (Redis 7)",
  "whatsapp_api": "reachable",
  "openai_api": "reachable",
  "uptime": "14d 6h 23m"
}
```

### Features
- **Live health checks** — DB, Redis, WhatsApp, OpenAI
- **Usage analytics** — messages/day, active users, feature adoption
- **Dead letter queue** — failed messages with one-click replay
- **Invoice browser** — search and download parsed invoices
- **AI insights** — per-user tax analytics

---

## Slide 15: Security & Compliance

### Security Layers
| Layer | Implementation |
|-------|---------------|
| **Webhook Verification** | HMAC-SHA256 signature on every inbound message |
| **GSTIN Validation** | Luhn checksum + format verification |
| **PAN Validation** | 10-char format validation |
| **Rate Limiting** | 30 msgs/min, 1000/day per user |
| **Dead Letter Queue** | No message lost — failed sends queued for retry |
| **JWT Auth** | CA dashboard secured with HS256 tokens |
| **Admin Auth** | Timing-safe token comparison |
| **Secret Validation** | App crashes if production runs with default secrets |
| **Session Isolation** | Redis-backed, per-user, with TTL expiry |

### Production Readiness
- Environment-aware security (dev vs production)
- All secrets validated at startup
- Structured logging with Loguru
- Graceful error handling — user always gets a response

---

## Slide 16: Testing & CI/CD

### Test Suite
```
$ pytest tests/ -v

119 passed in 0.45s
```

### Coverage Areas
| Module | Tests |
|--------|-------|
| GST Filing (GSTR-3B/1) | ✅ |
| ITR-1 & ITR-4 computation | ✅ |
| Tax slab calculations | ✅ |
| Invoice OCR parsing | ✅ |
| Form 16/26AS/AIS parsing | ✅ |
| PDF generation | ✅ |
| JSON generation | ✅ |
| Deduction caps (80C/80D) | ✅ |
| Regime comparison | ✅ |
| Data serialization | ✅ |

### CI/CD Pipeline (GitHub Actions)
```yaml
Trigger: push to main/develop, PR to main
Jobs:
  1) Lint (ruff + black)
  2) Test (pytest + PostgreSQL 16 + Redis 7)
  3) Build (Docker image)
```

---

## Slide 17: Deployment

### Docker Compose Stack (5 containers)
```yaml
services:
  app:        FastAPI (port 8000)
  worker:     RQ background jobs
  db:         PostgreSQL 16-alpine
  redis:      Redis 7-alpine
  ngrok:      Dev tunnel (optional)
```

### Quick Start
```bash
git clone <repo>
cp .env.example .env        # configure secrets
make first-run               # builds + migrates + starts
# Bot is live at localhost:8000
```

### 30+ Makefile Targets
```bash
make up           # start all services
make test         # run test suite
make logs         # tail all logs
make db-upgrade   # run migrations
make health       # check system health
make lint         # code quality check
```

---

## Slide 18: State Machine (22+ States)

```
MAIN_MENU
├── GST_MENU
│   ├── WAIT_GSTIN
│   ├── GST_FILING_MENU → GST_FILING_CONFIRM
│   ├── HSN_LOOKUP
│   ├── NIL_FILING_MENU → NIL_FILING_CONFIRM
│   └── SMART_UPLOAD (invoice batch)
│
├── ITR_MENU
│   ├── ITR1_ASK_SALARY → OTHER_INCOME → 80C → 80D → TDS
│   ├── ITR4_ASK_TYPE → TURNOVER → 80C → TDS
│   ├── ITR_DOC_TYPE_MENU → DOC_UPLOAD → DOC_REVIEW → DOC_EDIT
│   └── ITR_FILING_DOWNLOAD (PDF/JSON)
│
├── TAX_QA (conversational, multi-turn)
│
├── SETTINGS_MENU
│   ├── LANG_MENU (5 languages)
│   ├── MY_PROFILE
│   ├── FILING_HISTORY
│   └── INSIGHTS_MENU
│       ├── AI Tax Insights
│       └── Anomaly Check
│
└── Global: 0=Home, 9=Back, NIL=Quick file
```

---

## Slide 19: API Endpoints Summary

### Core (12 endpoints)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/webhook` | WhatsApp inbound messages |
| GET | `/webhook` | Webhook verification |
| GET | `/health` | Health check |

### GST API (4 endpoints)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/gst/mastergst/auth/login` | MasterGST auth |
| POST | `/gst/mastergst/gstr3b/save` | Save GSTR-3B |
| POST | `/gst/mastergst/gstr3b/file` | File GSTR-3B |
| GET | `/gst/mastergst/status/{ref}` | Filing status |

### ITR API (4 endpoints)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/itr/compute/itr1` | Compute ITR-1 |
| POST | `/itr/compute/itr4` | Compute ITR-4 |
| GET | `/itr/pdf/{id}` | Download PDF |
| GET | `/itr/json/{id}` | Get JSON |

### CA Dashboard (6 endpoints)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/ca/auth/register` | CA registration |
| POST | `/ca/auth/login` | CA login |
| GET | `/ca/dashboard` | Dashboard data |
| POST | `/ca/dashboard/clients` | Add client |
| GET | `/ca/dashboard/clients/{id}` | Client details |
| PUT | `/ca/dashboard/clients/{id}` | Update client |

### Admin API (10+ endpoints)
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/admin/system-health` | Health dashboard |
| GET | `/admin/ui/usage` | Usage stats |
| GET | `/admin/ui/dead-letters` | Failed messages |
| POST | `/admin/whatsapp/dead-letters/{id}/replay` | Retry message |
| GET | `/admin/invoices` | Invoice list |
| GET | `/admin/invoices/{id}/pdf` | Invoice PDF |

---

## Slide 20: Integrations Map

```
┌─────────────────────────────────────────────────────────┐
│                  GST + ITR WhatsApp Bot                 │
└──┬──────┬──────┬───────┬───────┬──────┬──────┬──────┬──┘
   │      │      │       │       │      │      │      │
   ▼      ▼      ▼       ▼       ▼      ▼      ▼      ▼
┌─────┐┌─────┐┌──────┐┌──────┐┌─────┐┌─────┐┌─────┐┌──────┐
│Meta ││Open ││Master││Sarvam││Bhas-││Tess-││Goog-││Report│
│What-││ AI  ││ GST  ││  AI  ││hini ││eract││le   ││ Lab  │
│sApp ││GPT4o││Sand- ││(STT) ││Trans││OCR  ││Cloud││(PDF) │
│API  ││     ││box   ││      ││late ││     ││Visn ││      │
└─────┘└─────┘└──────┘└──────┘└─────┘└─────┘└─────┘└──────┘
  Msg    AI     GST     Voice   i18n    Text   Alt    PDF
  Send   Parse  Filing  Input   API     OCR    OCR    Gen
  Media  Q&A    Status
  Verify Intent NIL
```

| Integration | Purpose | API |
|------------|---------|-----|
| **WhatsApp Cloud API** | Messaging, media, webhooks | Meta v20.0 |
| **OpenAI GPT-4o** | Vision, Q&A, intent, parsing | OpenAI API |
| **MasterGST** | GSTR-3B/1 filing, status | Sandbox API |
| **Sarvam AI** | Speech-to-text (5 languages) | Sarvam STT |
| **Bhashini** | Government translation API | MEITY API |
| **Tesseract** | Local OCR engine | pytesseract |
| **Google Vision** | Cloud OCR (optional) | GCP Vision |
| **ReportLab** | Invoice + ITR PDF generation | Python lib |

---

## Slide 21: Database Schema

```
┌──────────────┐    ┌────────────────┐    ┌──────────────┐
│    users     │    │   sessions     │    │   invoices   │
├──────────────┤    ├────────────────┤    ├──────────────┤
│ id (UUID)    │───▶│ id             │    │ id           │
│ whatsapp_no  │    │ user_id (FK)   │    │ user_id (FK) │
│ email        │    │ language       │    │ supplier_gstin│
│ name         │    │ step           │    │ receiver_gstin│
│ created_at   │    │ active         │    │ invoice_no   │
└──────────────┘    │ updated_at     │    │ taxable_value│
                    └────────────────┘    │ tax_amount   │
                                          │ total_amount │
┌──────────────┐    ┌────────────────┐    │ cgst/sgst    │
│  ca_users    │    │business_clients│    │ igst         │
├──────────────┤    ├────────────────┤    └──────────────┘
│ id           │───▶│ id             │
│ email        │    │ ca_id (FK)     │    ┌──────────────┐
│ name         │    │ name           │    │filing_records│
│ membership_no│    │ gstin          │    ├──────────────┤
│ last_login   │    │ pan            │    │ id           │
└──────────────┘    │ business_type  │    │ user_id      │
                    │ status         │    │ filing_type  │
                    └────────────────┘    │ form_type    │
                                          │ gstin / pan  │
┌──────────────────┐  ┌────────────────┐  │ period       │
│wa_message_logs   │  │wa_dead_letters │  │ status       │
├──────────────────┤  ├────────────────┤  │ reference_no │
│ id               │  │ id             │  │ filed_at     │
│ to_number        │  │ to_number      │  └──────────────┘
│ text             │  │ text           │
│ status           │  │ failure_reason │
│ created_at       │  │ retry_count    │
└──────────────────┘  └────────────────┘
```

**8 ORM Models** | PostgreSQL 16 | Alembic migrations

---

## Slide 22: Demo Walkthrough

### Live Demo Sequence

1. **Welcome** — Send "Hi" → see main menu in English
2. **GST Invoice Upload** — Send invoice photo → watch AI extract data
3. **GSTR-3B Preview** — See auto-computed tax summary
4. **NIL Filing** — Type "NIL" → one-click GSTR-3B filing
5. **ITR-1 Computation** — Walk through 5-question flow → old vs new regime
6. **Tax Q&A** — Ask "What is 80C limit?" → get conversational answer
7. **Language Switch** — Switch to Hindi → see entire bot in Hindi
8. **HSN Lookup** — "Cotton t-shirts" → get HSN code + GST rate
9. **Form 16 Upload** — Upload PDF → see extracted salary data → compute ITR
10. **Admin Dashboard** — Show system health, dead letters, usage stats

---

## Slide 23: Metrics & Scale

### Performance
| Metric | Value |
|--------|-------|
| Webhook response time | < 200ms (text), < 3s (OCR) |
| Invoice parsing accuracy | ~95% (Vision), ~85% (OCR+LLM) |
| Concurrent users | 100+ (async FastAPI) |
| Session TTL | 10 min idle timeout |
| Rate limit | 30 msgs/min per user |

### Codebase
| Metric | Value |
|--------|-------|
| Lines of code | ~15,000+ |
| Test cases | 119 passing |
| Test execution | < 0.5 seconds |
| API endpoints | 40+ |
| Conversation states | 22+ |
| i18n keys | 60+ (x 5 languages) |
| Docker containers | 5 |

---

## Slide 24: Roadmap

### Phase 2 (Planned)
- [ ] **E-Way Bill generation** via MasterGST
- [ ] **TDS filing** (Form 26Q, 24Q)
- [ ] **Multi-tenant** — separate data per CA firm
- [ ] **GSTR-2A reconciliation** — auto-match purchase invoices
- [ ] **Payment gateway** — subscription billing for premium features
- [ ] **Bulk invoice upload** via Excel/CSV
- [ ] **WhatsApp Business Interactive Messages** (buttons, lists)
- [ ] **Push notifications** — proactive deadline reminders
- [ ] **Audit trail** — complete log for compliance

### Phase 3 (Future)
- [ ] **Income Tax Portal integration** (e-filing)
- [ ] **Bank statement parsing** for auto-reconciliation
- [ ] **AI tax planning** — year-end optimization suggestions
- [ ] **Telegram / SMS channel** support
- [ ] **Open API** for third-party integrations

---

## Slide 25: Summary

### What Makes This Unique

| Differentiator | Details |
|---------------|---------|
| **WhatsApp-Native** | No app, no portal — just chat |
| **AI-First** | GPT-4o for parsing, Q&A, insights |
| **Multilingual** | 5 Indian languages, voice support |
| **End-to-End** | Invoice → GSTR-3B → Filing in one flow |
| **Dual Tax** | Both GST (monthly) & ITR (annual) |
| **CA-Ready** | Dashboard for professional tax practitioners |
| **Production-Grade** | 119 tests, CI/CD, Docker, rate limiting |
| **Open Architecture** | REST APIs, modular design, extensible |

### Built With
FastAPI | PostgreSQL | Redis | OpenAI GPT-4o | MasterGST | Tesseract | Docker | GitHub Actions

---

*Thank you!*

*Questions?*
