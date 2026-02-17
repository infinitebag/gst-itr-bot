# GST/ITR Bot — System Flow Diagrams

> All diagrams use [Mermaid](https://mermaid.js.org/) syntax.
> View them on GitHub, VS Code (Mermaid extension), or paste into [mermaid.live](https://mermaid.live).

---

## 1. High-Level Architecture

```mermaid
graph TB
    subgraph Clients
        WA[WhatsApp User]
        MOB[Mobile App]
        WEB[Web App]
    end

    subgraph "API Layer (FastAPI)"
        WH["/webhook<br/>WhatsApp Handler"]
        GST_API["/gst/*<br/>GST Filing API"]
        ITR_API["/itr/*<br/>ITR Compute API"]
        CA_API["/api/v1/ca/*<br/>CA REST API<br/>Auth, Clients, Reviews"]
        ADM_API["/api/v1/admin/ca/*<br/>Admin CA Mgmt"]
        ADMIN["/admin/*<br/>CA Dashboard (HTML)"]
    end

    subgraph "Domain Services"
        GST_SVC["GST Service<br/>prepare_gstr3b<br/>nil_filing"]
        ITR_SVC["ITR Service<br/>compute_itr1/4"]
        ITR_PDF["ITR PDF<br/>generate_itr1/4_pdf"]
        ITR_JSON["ITR JSON<br/>generate_itr1/4_json"]
        GST_EXP["GST Export<br/>make_gstr3b/1_json"]
        INV_PARSE["Invoice Parser<br/>OCR + Vision"]
        FORM_PARSE["Form Parser<br/>Form16/26AS/AIS"]
    end

    subgraph "External APIs"
        MGST["MasterGST<br/>Sandbox API"]
        OPENAI["OpenAI<br/>GPT-4o Vision"]
        WA_API["WhatsApp<br/>Cloud API"]
    end

    subgraph "Infrastructure"
        PG[(PostgreSQL)]
        REDIS[(Redis<br/>Session Cache)]
        OCR["Tesseract OCR"]
    end

    WA -->|webhook| WH
    MOB -->|REST| GST_API
    MOB -->|REST| ITR_API
    MOB -->|REST /api/v1| CA_API
    WEB -->|REST| GST_API
    WEB -->|REST| ITR_API
    WEB -->|REST /api/v1| CA_API
    WEB -->|admin| ADM_API

    WH --> GST_SVC
    WH --> ITR_SVC
    WH --> INV_PARSE
    WH --> FORM_PARSE
    WH --> ITR_PDF
    WH --> ITR_JSON

    GST_API --> GST_SVC
    GST_API --> GST_EXP
    GST_API --> MGST

    ITR_API --> ITR_SVC
    ITR_API --> ITR_PDF
    ITR_API --> ITR_JSON

    INV_PARSE --> OPENAI
    INV_PARSE --> OCR
    FORM_PARSE --> OPENAI
    FORM_PARSE --> OCR

    CA_API --> PG
    CA_API --> GST_SVC
    CA_API --> ITR_SVC
    ADM_API --> PG

    GST_SVC --> MGST
    WH --> WA_API
    WH --> REDIS
    GST_API --> PG
    ITR_API --> PG
```

---

## 2. WhatsApp Bot — Master State Machine

```mermaid
stateDiagram-v2
    [*] --> MAIN_MENU

    MAIN_MENU --> GST_MENU : 1 GST Services
    MAIN_MENU --> ITR_MENU : 2 ITR Services
    MAIN_MENU --> WAIT_INVOICE_UPLOAD : 3 Upload Invoice
    MAIN_MENU --> LANG_MENU : 4 Language
    MAIN_MENU --> TAX_QA : 5 Tax Q&A
    MAIN_MENU --> INSIGHTS_MENU : 6 Insights
    MAIN_MENU --> BATCH_UPLOAD : 7 Batch Upload

    LANG_MENU --> MAIN_MENU : select 1-5

    TAX_QA --> TAX_QA : ask question
    TAX_QA --> MAIN_MENU : 0

    INSIGHTS_MENU --> MAIN_MENU : 0

    WAIT_INVOICE_UPLOAD --> MAIN_MENU : upload done

    BATCH_UPLOAD --> BATCH_UPLOAD : upload more
    BATCH_UPLOAD --> MAIN_MENU : "done"

    note right of MAIN_MENU
        Global shortcuts:
        0 = Main Menu
        9 = Go Back
        "NIL" = NIL Filing
    end note
```

---

## 3. GST Filing Flow (WhatsApp)

```mermaid
flowchart TD
    GM[GST_MENU] -->|1| WG[WAIT_GSTIN]
    GM -->|2| GFM[GST_FILING_MENU]
    GM -->|3| HSN[HSN_LOOKUP]
    GM -->|4| NFM[NIL_FILING_MENU]

    WG -->|valid GSTIN| MM[MAIN_MENU]
    WG -->|invalid| WG

    HSN -->|product text| HSN
    HSN -->|0/9| MM

    GFM -->|1 GSTR-3B| PREVIEW_3B["Show GSTR-3B Preview<br/>+ Confirm Prompt"]
    GFM -->|2 GSTR-1| PREVIEW_1["Show GSTR-1 Preview<br/>+ Confirm Prompt"]
    GFM -->|3 NIL| NFM

    PREVIEW_3B --> GFC[GST_FILING_CONFIRM]
    PREVIEW_1 --> GFC

    GFC -->|YES| SUBMIT{"Submit to<br/>MasterGST Sandbox"}
    GFC -->|other| GFM

    SUBMIT -->|success| MM
    SUBMIT -->|error| GFM

    NFM -->|1| NFC[NIL_FILING_CONFIRM]
    NFM -->|2| NFC
    NFM -->|3 both| NFC

    NFC -->|YES| NIL_SUBMIT{"Try MasterGST<br/>Fallback: Local"}
    NFC -->|other| NFM

    NIL_SUBMIT -->|success| MM
    NIL_SUBMIT -->|error| GM

    style SUBMIT fill:#4CAF50,color:#fff
    style NIL_SUBMIT fill:#4CAF50,color:#fff
    style MM fill:#2196F3,color:#fff
```

---

## 4. ITR Computation Flow (WhatsApp)

```mermaid
flowchart TD
    IM[ITR_MENU] -->|1 Salaried| S1[ITR1_ASK_SALARY]
    IM -->|2 Business| T1[ITR4_ASK_TYPE]
    IM -->|3 Upload Docs| DTM[ITR_DOC_TYPE_MENU]

    %% ITR-1 Manual Flow
    S1 -->|amount| S2[ITR1_ASK_OTHER_INCOME]
    S2 -->|amount| S3[ITR1_ASK_80C]
    S3 -->|amount| S4[ITR1_ASK_80D]
    S4 -->|amount| S5[ITR1_ASK_TDS]
    S5 -->|amount| COMPUTE1{"compute_itr1()"}

    %% ITR-4 Manual Flow
    T1 -->|1 Business 8%| T2[ITR4_ASK_TURNOVER]
    T1 -->|2 Profession 50%| T2
    T2 -->|amount| T3[ITR4_ASK_80C]
    T3 -->|amount| T4[ITR4_ASK_TDS]
    T4 -->|amount| COMPUTE4{"compute_itr4()"}

    %% Document Upload Flow
    DTM -->|1 Form16| DU[ITR_DOC_UPLOAD]
    DTM -->|2 26AS| DU
    DTM -->|3 AIS| DU
    DU -->|upload image/pdf| DR[ITR_DOC_REVIEW]
    DR -->|1 upload more| DTM
    DR -->|2 edit field| DEF[ITR_DOC_EDIT_FIELD]
    DEF -->|field value| DR
    DR -->|3 compute| DPI[ITR_DOC_PICK_ITR]
    DPI -->|1 ITR-1| COMPUTE_DOC1{"compute_itr1()"}
    DPI -->|2 ITR-4| COMPUTE_DOC4{"compute_itr4()"}

    %% All paths converge to download
    COMPUTE1 --> DL[ITR_FILING_DOWNLOAD]
    COMPUTE4 --> DL
    COMPUTE_DOC1 --> DL
    COMPUTE_DOC4 --> DL

    DL -->|"4 PDF"| PDF["Generate PDF<br/>Send via WhatsApp"]
    DL -->|"5 JSON"| JSON["Generate JSON<br/>Send via WhatsApp"]
    DL -->|0| MM[MAIN_MENU]

    PDF --> MM
    JSON --> MM

    style COMPUTE1 fill:#FF9800,color:#fff
    style COMPUTE4 fill:#FF9800,color:#fff
    style COMPUTE_DOC1 fill:#FF9800,color:#fff
    style COMPUTE_DOC4 fill:#FF9800,color:#fff
    style DL fill:#9C27B0,color:#fff
    style MM fill:#2196F3,color:#fff
```

---

## 5. ITR Document Upload & Merge Flow

```mermaid
flowchart LR
    subgraph "Upload Phase"
        F16[Form 16<br/>Salary + TDS]
        F26[Form 26AS<br/>Tax Credits]
        AIS[AIS<br/>Annual Info]
    end

    subgraph "Parse Phase"
        V["GPT-4o Vision<br/>(Primary)"]
        OCR["Tesseract OCR<br/>+ LLM Parse<br/>(Fallback)"]
    end

    subgraph "Merge Phase"
        M16["merge_form16()"]
        M26["merge_form26as()"]
        MAIS["merge_ais()"]
        MERGED["MergedITRData<br/>salary, TDS, 80C,<br/>80D, other income,<br/>house property..."]
    end

    subgraph "Review & Edit"
        REV["Review Summary<br/>All extracted fields"]
        EDIT["Edit Field<br/>'field_num value'"]
    end

    subgraph "Compute"
        ITR1["ITR-1 Sahaj<br/>compute_itr1()"]
        ITR4["ITR-4 Sugam<br/>compute_itr4()"]
    end

    F16 --> V --> M16 --> MERGED
    F16 --> OCR --> M16
    F26 --> V --> M26 --> MERGED
    F26 --> OCR --> M26
    AIS --> V --> MAIS --> MERGED
    AIS --> OCR --> MAIS

    MERGED --> REV
    REV --> EDIT --> REV
    REV --> ITR1
    REV --> ITR4

    ITR1 --> DL[PDF / JSON<br/>Download]
    ITR4 --> DL
```

---

## 6. REST API Flows (Mobile / Web)

### 6a. GST Filing via REST API

```mermaid
sequenceDiagram
    participant Client as Mobile/Web App
    participant API as FastAPI /gst/*
    participant DB as PostgreSQL
    participant MGST as MasterGST Sandbox

    Client->>API: POST /gst/gstr3b/file<br/>user_id, period, gstin

    API->>API: Validate period (YYYY-MM)<br/>Validate GSTIN (15-char regex)<br/>Check MasterGST credentials

    API->>DB: InvoiceRepository.list_for_period()
    DB-->>API: invoices[]

    API->>API: prepare_gstr3b(invoices)<br/>make_gstr3b_json(gstin, period, summary)

    API->>MGST: POST /api/v1/authenticate
    MGST-->>API: auth_token

    API->>MGST: POST /api/v1/gstr3b/save
    MGST-->>API: save_response

    API->>MGST: POST /api/v1/gstr3b/file
    MGST-->>API: submit_response + reference_id

    API->>DB: FilingRepository.create_record()

    API-->>Client: GstFilingResponse {<br/>status, reference_number,<br/>form_type, period, gstin}
```

### 6b. ITR Compute + Download via REST API

```mermaid
sequenceDiagram
    participant Client as Mobile/Web App
    participant API as FastAPI /itr/*

    Note over Client,API: Step 1: Compute Tax

    Client->>API: POST /itr/itr1/compute<br/>{salary, deductions, TDS...}
    API->>API: compute_itr1(input)<br/>Old vs New regime comparison
    API-->>Client: ITRComputeResponse {<br/>old_regime, new_regime,<br/>recommended, savings,<br/>formatted_text}

    Note over Client,API: Step 2: Download PDF

    Client->>API: POST /itr/itr1/pdf<br/>{same input data}
    API->>API: compute_itr1(input)<br/>generate_itr1_pdf(input, result)
    API-->>Client: PDF binary (StreamingResponse)

    Note over Client,API: Step 3: Download JSON

    Client->>API: POST /itr/itr1/json<br/>{same input data}
    API->>API: compute_itr1(input)<br/>generate_itr1_json(input, result)
    API-->>Client: Structured JSON {<br/>formType, personalInfo,<br/>incomeDetails, deductions,<br/>taxComputation, verification}

    Note over Client,API: Step 4: Save Filing Record

    Client->>API: POST /itr/itr/save-filing<br/>user_id, form_type, pan
    API->>API: FilingRepository.create_record()
    API-->>Client: {id, status: "generated"}
```

---

## 7. Invoice Parsing Pipeline

```mermaid
flowchart TD
    INPUT["User sends<br/>Image / PDF"]

    INPUT --> DETECT{"Image or<br/>Document?"}

    DETECT -->|Image| VISION["GPT-4o Vision<br/>parse_invoice_vision()"]
    DETECT -->|PDF/Doc| OCR_PATH["Tesseract OCR<br/>extract_text()"]

    VISION -->|success| VALIDATE
    VISION -->|fail| OCR_PATH

    OCR_PATH --> REGEX["Regex Parser<br/>parse_invoice_text()"]
    OCR_PATH --> LLM["LLM Parser<br/>parse_invoice_llm()"]

    REGEX --> MERGE_PARSE["Merge Results<br/>LLM fills gaps"]
    LLM --> MERGE_PARSE

    MERGE_PARSE --> VALIDATE["Validate GSTINs<br/>Check required fields"]

    VALIDATE --> STORE["Store in Session<br/>uploaded_invoices[]"]

    STORE --> PDF_GEN["Generate Invoice PDF<br/>Send via WhatsApp"]

    STORE --> GSTR["Available for<br/>GSTR-3B / GSTR-1<br/>Filing"]

    style VISION fill:#4CAF50,color:#fff
    style OCR_PATH fill:#FF9800,color:#fff
    style VALIDATE fill:#2196F3,color:#fff
```

---

## 8. NIL Filing Flow (MasterGST Sandbox)

```mermaid
flowchart TD
    START["NIL_FILING_MENU<br/>Select form type"] -->|1| G3B["GSTR-3B only"]
    START -->|2| G1["GSTR-1 only"]
    START -->|3| BOTH["GSTR-3B + GSTR-1"]

    G3B --> CONFIRM[NIL_FILING_CONFIRM<br/>Type YES to confirm]
    G1 --> CONFIRM
    BOTH --> CONFIRM

    CONFIRM -->|YES| TRY_MGST{"Try MasterGST<br/>Sandbox API"}

    TRY_MGST -->|success| AUTH["authenticate(gstin)"]
    AUTH --> FILE_3B["file_nil_gstr3b()<br/>(if selected)"]
    AUTH --> FILE_1["file_nil_gstr1()<br/>(if selected)"]
    FILE_3B --> SUCCESS
    FILE_1 --> SUCCESS

    TRY_MGST -->|connection fail| FALLBACK["Local Simulation<br/>prepare_nil_gstr3b/1()"]
    FALLBACK --> SUCCESS

    SUCCESS["Filing Successful<br/>Reference Number<br/>+ Main Menu"]

    CONFIRM -->|other| START

    style TRY_MGST fill:#FF9800,color:#fff
    style SUCCESS fill:#4CAF50,color:#fff
    style FALLBACK fill:#9E9E9E,color:#fff
```

---

## 9. Complete REST API Endpoint Map

```mermaid
graph LR
    subgraph "End-User GST /api/v1/gst"
        G1["POST /gstr3b<br/>File GSTR-3B"]
        G2["POST /nil-filing<br/>File NIL return"]
        G3["GET /current-period<br/>Current GST period"]
    end

    subgraph "End-User ITR /api/v1/itr"
        I1["POST /itr1<br/>Compute ITR-1"]
        I2["POST /itr4<br/>Compute ITR-4"]
    end

    subgraph "CA Auth /api/v1/ca/auth"
        CA1["POST /login<br/>JWT pair"]
        CA2["POST /register<br/>New CA"]
        CA3["POST /refresh<br/>Rotate tokens"]
        CA4["GET /me<br/>CA profile"]
    end

    subgraph "CA Clients /api/v1/ca/clients"
        CL1["GET /<br/>List + search"]
        CL2["POST /<br/>Create client"]
        CL3["GET /{id}<br/>Detail"]
        CL4["PUT /{id}<br/>Update"]
        CL5["DELETE /{id}<br/>Deactivate"]
        CL6["POST /bulk-upload<br/>CSV import"]
        CL7["GET /{id}/analytics"]
        CL8["GET /{id}/invoices.pdf"]
    end

    subgraph "CA Reviews /api/v1/ca"
        R1["GET /itr-reviews<br/>List ITR drafts"]
        R2["GET /itr-reviews/{id}<br/>ITR detail"]
        R3["POST .../approve<br/>Approve ITR"]
        R4["POST .../request-changes"]
        R5["PUT /itr-reviews/{id}<br/>Edit + recompute"]
        R6["GET /gst-reviews<br/>List GST filings"]
        R7["GET /gst-reviews/{id}<br/>GST detail"]
        R8["POST .../approve<br/>Approve GST"]
        R9["POST .../request-changes"]
        R10["POST .../submit<br/>Submit to MasterGST"]
        R11["GET /deadlines<br/>Upcoming dates"]
    end

    subgraph "Admin CA /api/v1/admin/ca"
        AD1["GET /list<br/>All CAs + stats"]
        AD2["GET /pending<br/>Awaiting approval"]
        AD3["POST /{id}/approve"]
        AD4["POST /{id}/reject"]
        AD5["POST /{id}/toggle-active"]
        AD6["POST /clients/{id}/transfer"]
    end

    subgraph "WhatsApp /webhook"
        W1["GET /webhook<br/>Verification"]
        W2["POST /webhook<br/>Message Handler"]
    end

    CA1 -.->|JWT Bearer| CL1
    CA1 -.->|JWT Bearer| R1
    R10 -.->|submits to| MGST["MasterGST API"]
    G1 -.->|requires| DB[(PostgreSQL)]
    CL2 -.->|writes| DB
    R1 -.->|reads| DB
    AD1 -.->|X-Admin-Token| DB
    W2 -.->|uses| REDIS[(Redis Sessions)]
    I1 -.->|stateless| COMPUTE[Pure Computation]

    subgraph "Multi-GSTIN /api/v1/user-gstins"
        MG1["GET /<br/>List GSTINs"]
        MG2["POST /<br/>Add GSTIN"]
        MG3["DELETE /{gstin}<br/>Remove"]
        MG4["PUT /primary<br/>Set primary"]
        MG5["GET /summary<br/>Consolidated"]
    end

    subgraph "Refunds /api/v1/refunds"
        RF1["GET /<br/>List claims"]
        RF2["POST /<br/>Create claim"]
        RF3["GET /{id}<br/>Claim detail"]
    end

    subgraph "Notices /api/v1/notices"
        NT1["GET /<br/>List notices"]
        NT2["POST /<br/>Create notice"]
        NT3["PUT /{id}<br/>Update status"]
    end

    subgraph "Notifications /api/v1/notifications"
        NF1["GET /preferences"]
        NF2["PUT /preferences"]
        NF3["GET /scheduled"]
        NF4["POST /schedule-reminders"]
    end

    CA1 -.->|JWT Bearer| MG1
    CA1 -.->|JWT Bearer| RF1
    CA1 -.->|JWT Bearer| NT1
    CA1 -.->|JWT Bearer| NF1
    MG2 -.->|writes| DB
    RF2 -.->|writes| DB
    NT2 -.->|writes| DB
```

---

## 10. Session Data Structure

```mermaid
classDiagram
    class Session {
        +string state
        +string lang
        +list~string~ stack
        +dict data
    }

    class SessionData {
        +string gstin
        +dict last_invoice
        +list~dict~ uploaded_invoices
        +list~dict~ batch_invoices
        +dict itr1
        +dict itr4
        +dict itr_docs
        +dict itr_last_result
        +string nil_period
        +string nil_form_type
        +list~dict~ nil_filings
        +string gst_filing_form
        +list~dict~ qa_history
    }

    class ITR1Data {
        +float salary
        +float other_income
        +float sec_80c
        +float sec_80d
        +float tds
    }

    class ITR4Data {
        +string type
        +int rate
        +float turnover
        +float sec_80c
        +float tds
    }

    class ITRDocsData {
        +string pending_type
        +list~string~ uploaded
        +dict merged
    }

    class ITRLastResult {
        +string form_type
        +dict input_data
        +string input_type
    }

    Session --> SessionData : data
    SessionData --> ITR1Data : itr1
    SessionData --> ITR4Data : itr4
    SessionData --> ITRDocsData : itr_docs
    SessionData --> ITRLastResult : itr_last_result
```

---

## 11. CA REST API Flow (Mobile / Web)

```mermaid
sequenceDiagram
    participant App as Mobile/Web App
    participant API as /api/v1/ca
    participant DB as PostgreSQL
    participant WA as WhatsApp API
    participant MGST as MasterGST

    Note over App,API: Authentication
    App->>API: POST /auth/login {email, password}
    API->>DB: Verify credentials (bcrypt)
    API-->>App: {access_token, refresh_token, expires_in}

    Note over App,API: Client Management
    App->>API: GET /clients?q=ravi&limit=20
    API->>DB: Search BusinessClient
    API-->>App: {items: [...], total, has_more}

    App->>API: POST /clients {name, whatsapp, pan}
    API->>API: Normalize WhatsApp, validate PAN
    API->>DB: Insert BusinessClient
    API-->>App: {id, name, whatsapp_number, ...}

    App->>API: POST /clients/bulk-upload (CSV)
    API->>API: Parse CSV, validate rows
    API->>DB: Batch insert
    API-->>App: {added: 3, skipped: 1, failed: 1}

    Note over App,API: ITR Review Workflow
    App->>API: GET /itr-reviews?status=pending_ca_review
    API->>DB: ITRDraft WHERE ca_id = ?
    API-->>App: Paginated ITR drafts

    App->>API: POST /itr-reviews/{id}/approve {ca_notes}
    API->>DB: Transition draft status
    API->>WA: Notify user: "CA approved your ITR-1"
    API-->>App: Updated draft (status: ca_approved)

    App->>API: PUT /itr-reviews/{id} {input_overrides}
    API->>API: Merge overrides + recompute tax
    API->>DB: Update input_json + result_json
    API-->>App: Updated draft with new computation

    Note over App,API: GST Review + Submit
    App->>API: GET /gst-reviews?status=pending_ca_review
    API-->>App: Paginated GST filings

    App->>API: POST /gst-reviews/{id}/approve
    API->>DB: Transition filing status
    API->>WA: Notify user: "CA approved GSTR-3B"
    API-->>App: Updated filing (status: ca_approved)

    App->>API: POST /gst-reviews/{id}/submit
    API->>MGST: File GSTR-3B / GSTR-1
    API->>DB: Update status + reference_number
    API->>WA: Notify user: "Filed!"
    API-->>App: {status: submitted, reference_number}

    Note over App,API: Token Refresh
    App->>API: POST /auth/refresh {refresh_token}
    API-->>App: New {access_token, refresh_token}
```

---

## 12. e-Invoice Flow (Phase 6)

```mermaid
flowchart TD
    EIM[EINVOICE_MENU] -->|1 Generate| EIU[EINVOICE_UPLOAD]
    EIM -->|2 Status| EISA[EINVOICE_STATUS_ASK]
    EIM -->|3 Cancel| EIC[EINVOICE_CANCEL]

    EIU -->|upload invoice| EIC2[EINVOICE_CONFIRM]
    EIU -->|"done"| EIM

    EIC2 -->|"yes"| GEN{"Generate IRN<br/>via EInvoiceClient"}
    EIC2 -->|"no"| EIM

    GEN -->|success| RESULT["✅ IRN Generated<br/>Show IRN + QR code"]
    GEN -->|error| ERR["❌ Generation failed<br/>Show error"]

    EISA -->|IRN number| STATUS{"Check IRN status"}
    STATUS --> RESULT2["Show IRN status"]

    EIC -->|IRN number| CANCEL{"Cancel IRN"}
    CANCEL --> RESULT3["IRN Cancelled"]

    RESULT --> EIM
    RESULT2 --> EIM
    RESULT3 --> EIM
    ERR --> EIM

    style GEN fill:#4CAF50,color:#fff
    style EIM fill:#2196F3,color:#fff
```

---

## 13. e-WayBill Flow (Phase 6)

```mermaid
flowchart TD
    EWM[EWAYBILL_MENU] -->|1 Generate| EWU[EWAYBILL_UPLOAD]
    EWM -->|2 Track| EWTA[EWAYBILL_TRACK_ASK]
    EWM -->|3 Update Vehicle| EWVA[EWAYBILL_VEHICLE_ASK]

    EWU -->|upload invoice| EWT[EWAYBILL_TRANSPORT]
    EWU -->|"done"| EWM

    EWT -->|transport details| GEN{"Generate EWB<br/>via EWayBillClient"}

    GEN -->|success| RESULT["✅ EWB Generated<br/>Show EWB number + validity"]
    GEN -->|error| ERR["❌ Generation failed"]

    EWTA -->|EWB number| TRACK{"Track EWB status"}
    TRACK --> RESULT2["Show EWB status"]

    EWVA -->|vehicle info| VUPD{"Update vehicle"}
    VUPD --> RESULT3["Vehicle updated"]

    RESULT --> EWM
    RESULT2 --> EWM
    RESULT3 --> EWM
    ERR --> EWM

    style GEN fill:#4CAF50,color:#fff
    style EWM fill:#2196F3,color:#fff
```

---

## 14. Small-Segment Guided Wizard (Phase 7)

```mermaid
flowchart TD
    START["User selects<br/>Monthly Filing<br/>(small segment)"] --> SALES[SMALL_WIZARD_SALES]

    SALES -->|upload invoices| SALES
    SALES -->|"done"| SUMMARY1["Sales Tax: ₹15,300<br/>from 5 invoices ✅"]

    SUMMARY1 --> PURCH[SMALL_WIZARD_PURCHASES]
    PURCH -->|upload invoices| PURCH
    PURCH -->|"done"| SUMMARY2["📊 GST Summary:<br/>Sales Tax: ₹15,300<br/>Purchase Credit: ₹8,200<br/>Amount to Pay: ₹7,100"]

    SUMMARY2 --> CONFIRM[SMALL_WIZARD_CONFIRM]
    CONFIRM -->|"1 Send to CA"| CA["✅ Sent to CA for review"]
    CONFIRM -->|"2 Edit"| SALES
    CONFIRM -->|"3 Cancel"| MM[MAIN_MENU]

    CA --> MM

    style START fill:#4CAF50,color:#fff
    style MM fill:#2196F3,color:#fff
    style SUMMARY2 fill:#FF9800,color:#fff
```

---

## 15. Medium-Segment Credit Check (Phase 7)

```mermaid
flowchart TD
    START["User selects<br/>Monthly Filing<br/>(medium segment)"] --> CHECK[MEDIUM_CREDIT_CHECK]

    CHECK -->|"auto-run"| IMPORT["Import GSTR-2B<br/>via gstr2b_service"]
    IMPORT --> RECON["Run reconciliation<br/>Match invoices"]
    RECON --> RESULT[MEDIUM_CREDIT_RESULT]

    RESULT -->|"1 Continue filing"| FILING["GST_PERIOD_MENU<br/>Regular filing flow"]
    RESULT -->|"2 View mismatches"| DETAIL["Show mismatch details:<br/>⚠️ Value mismatches<br/>📤 Missing in 2B<br/>📥 Missing in books"]
    RESULT -->|"3 Notify suppliers"| NOTIFY["📨 Send notification<br/>about missing invoices"]

    DETAIL -->|"1 Continue"| FILING
    NOTIFY --> RESULT

    style CHECK fill:#FF9800,color:#fff
    style RESULT fill:#9C27B0,color:#fff
    style FILING fill:#4CAF50,color:#fff
```

---

## 16. Multi-GSTIN Management (Phase 8)

```mermaid
flowchart TD
    MGM[MULTI_GSTIN_MENU] -->|"1 Add"| MGA[MULTI_GSTIN_ADD]
    MGM -->|"2 Switch"| SWITCH["Enter GSTIN to switch"]
    MGM -->|"3 Summary"| MGS[MULTI_GSTIN_SUMMARY]

    MGA -->|valid GSTIN| MGL[MULTI_GSTIN_LABEL]
    MGA -->|invalid| MGA

    MGL -->|label text| SAVE{"Save to DB<br/>via multi_gstin_service"}
    SAVE -->|success| MGM
    SAVE -->|error| MGM

    SWITCH -->|valid GSTIN| MGM
    MGS --> MGM

    style MGM fill:#2196F3,color:#fff
    style SAVE fill:#4CAF50,color:#fff
```

---

## 17. Refund & Notice Flow (Phase 9)

```mermaid
flowchart TD
    RM[REFUND_MENU] -->|"1 New claim"| RT[REFUND_TYPE]
    RM -->|"2 Track claims"| LIST["List refund claims"]

    RT -->|"1 Excess"| RD[REFUND_DETAILS]
    RT -->|"2 Export"| RD
    RT -->|"3 Inverted Duty"| RD

    RD -->|amount| CREATE{"Create refund claim<br/>via refund_service"}
    CREATE --> RESULT["✅ Claim created<br/>Type + Amount + Status"]
    RESULT --> MM[MAIN_MENU]
    LIST --> RM

    NM[NOTICE_MENU] -->|"1 List"| NL["List pending notices"]
    NM -->|"2 Upload"| NU[NOTICE_UPLOAD]
    NU -->|"done"| NM
    NL --> NM

    EM[EXPORT_MENU] --> MM2["Coming soon"]

    style CREATE fill:#4CAF50,color:#fff
    style MM fill:#2196F3,color:#fff
```

---

## 18. Notification Settings (Phase 10)

```mermaid
flowchart TD
    NS[NOTIFICATION_SETTINGS] -->|"1"| FR["Filing reminders only"]
    NS -->|"2"| RA["Risk alerts only"]
    NS -->|"3"| SU["Status updates only"]
    NS -->|"4"| ALL["All notifications"]
    NS -->|"5"| OFF["Turn off notifications"]

    FR --> SAVE{"Save preferences<br/>to session"}
    RA --> SAVE
    SU --> SAVE
    ALL --> SAVE
    OFF --> SAVE

    SAVE --> SM[SETTINGS_MENU]

    style NS fill:#2196F3,color:#fff
    style SAVE fill:#4CAF50,color:#fff
```

---

## 19. Handler Chain Architecture

```mermaid
flowchart LR
    WH["POST /webhook<br/>whatsapp.py"] --> CHAIN["Handler Chain<br/>Dispatch Loop"]

    CHAIN --> H1["einvoice.py"]
    CHAIN --> H2["ewaybill.py"]
    CHAIN --> H3["gst_wizard.py"]
    CHAIN --> H4["gst_credit_check.py"]
    CHAIN --> H5["multi_gstin.py"]
    CHAIN --> H6["refund_notice.py"]
    CHAIN --> H7["notification_settings.py"]

    H1 -->|"Response or None"| CHAIN
    H2 -->|"Response or None"| CHAIN
    H3 -->|"Response or None"| CHAIN
    H4 -->|"Response or None"| CHAIN
    H5 -->|"Response or None"| CHAIN
    H6 -->|"Response or None"| CHAIN
    H7 -->|"Response or None"| CHAIN

    CHAIN -->|"all None"| INLINE["Inline Handlers<br/>(whatsapp.py)"]

    style WH fill:#2196F3,color:#fff
    style CHAIN fill:#FF9800,color:#fff
```

---

## Quick Reference: State Transition Table

| From State | User Input | To State | Action |
|---|---|---|---|
| MAIN_MENU | 1 | GST_MENU | Show GST services |
| MAIN_MENU | 2 | ITR_MENU | Show ITR services |
| MAIN_MENU | 3 | WAIT_INVOICE_UPLOAD | Prompt for image/PDF |
| MAIN_MENU | 4 | LANG_MENU | Show 5 languages |
| MAIN_MENU | 5 | TAX_QA | Start AI Q&A |
| MAIN_MENU | 6 | INSIGHTS_MENU | Show analytics options |
| MAIN_MENU | 7 | BATCH_UPLOAD | Start batch mode |
| GST_MENU | 1 | WAIT_GSTIN | Ask for GSTIN |
| GST_MENU | 2 | GST_FILING_MENU | Show filing options |
| GST_MENU | 3 | HSN_LOOKUP | Ask for product |
| GST_MENU | 4 | NIL_FILING_MENU | Show NIL options |
| GST_FILING_MENU | 1 | GST_FILING_CONFIRM | Preview GSTR-3B |
| GST_FILING_MENU | 2 | GST_FILING_CONFIRM | Preview GSTR-1 |
| GST_FILING_MENU | 3 | NIL_FILING_MENU | NIL shortcut |
| GST_FILING_CONFIRM | YES | MAIN_MENU | Submit to MasterGST |
| NIL_FILING_MENU | 1/2/3 | NIL_FILING_CONFIRM | Confirm form type |
| NIL_FILING_CONFIRM | YES | MAIN_MENU | File NIL return |
| ITR_MENU | 1 | ITR1_ASK_SALARY | Start ITR-1 |
| ITR_MENU | 2 | ITR4_ASK_TYPE | Start ITR-4 |
| ITR_MENU | 3 | ITR_DOC_TYPE_MENU | Upload documents |
| ITR1_ASK_SALARY | number | ITR1_ASK_OTHER_INCOME | Store salary |
| ITR1_ASK_OTHER_INCOME | number | ITR1_ASK_80C | Store other income |
| ITR1_ASK_80C | number | ITR1_ASK_80D | Store 80C |
| ITR1_ASK_80D | number | ITR1_ASK_TDS | Store 80D |
| ITR1_ASK_TDS | number | ITR_FILING_DOWNLOAD | Compute + show result |
| ITR4_ASK_TYPE | 1/2 | ITR4_ASK_TURNOVER | Set biz/prof type |
| ITR4_ASK_TURNOVER | number | ITR4_ASK_80C | Store turnover |
| ITR4_ASK_80C | number | ITR4_ASK_TDS | Store 80C |
| ITR4_ASK_TDS | number | ITR_FILING_DOWNLOAD | Compute + show result |
| ITR_DOC_TYPE_MENU | 1/2/3 | ITR_DOC_UPLOAD | Set doc type |
| ITR_DOC_UPLOAD | image/pdf | ITR_DOC_REVIEW | Parse + merge |
| ITR_DOC_REVIEW | 1 | ITR_DOC_TYPE_MENU | Upload another |
| ITR_DOC_REVIEW | 2 | ITR_DOC_EDIT_FIELD | Edit a field |
| ITR_DOC_REVIEW | 3 | ITR_DOC_PICK_ITR | Choose ITR form |
| ITR_DOC_EDIT_FIELD | "N val" | ITR_DOC_REVIEW | Update field |
| ITR_DOC_PICK_ITR | 1/2 | ITR_FILING_DOWNLOAD | Compute + show result |
| ITR_FILING_DOWNLOAD | 4 | MAIN_MENU | Send PDF via WhatsApp |
| ITR_FILING_DOWNLOAD | 5 | MAIN_MENU | Send JSON via WhatsApp |
| ITR_FILING_DOWNLOAD | 0 | MAIN_MENU | Skip download |
| LANG_MENU | 1-5 | MAIN_MENU | Set language |
| TAX_QA | text | TAX_QA | AI answer + loop |
| TAX_QA | 0 | MAIN_MENU | Exit Q&A |
| Any State | 0 | MAIN_MENU | Global home |
| Any State | 9 | (previous) | Pop navigation stack |
| **Phase 6: e-Invoice** | | | |
| EINVOICE_MENU | 1 | EINVOICE_UPLOAD | Upload invoice for IRN |
| EINVOICE_MENU | 2 | EINVOICE_STATUS_ASK | Check IRN status |
| EINVOICE_MENU | 3 | EINVOICE_CANCEL | Cancel IRN |
| EINVOICE_UPLOAD | upload | EINVOICE_CONFIRM | Review parsed invoice |
| EINVOICE_CONFIRM | yes | EINVOICE_MENU | Generate IRN |
| **Phase 6: e-WayBill** | | | |
| EWAYBILL_MENU | 1 | EWAYBILL_UPLOAD | Upload for EWB |
| EWAYBILL_MENU | 2 | EWAYBILL_TRACK_ASK | Track EWB |
| EWAYBILL_MENU | 3 | EWAYBILL_VEHICLE_ASK | Update vehicle |
| EWAYBILL_UPLOAD | upload | EWAYBILL_TRANSPORT | Enter transport details |
| EWAYBILL_TRANSPORT | details | EWAYBILL_MENU | Generate EWB |
| **Phase 7: Segment Flows** | | | |
| SMALL_WIZARD_SALES | "done" | SMALL_WIZARD_PURCHASES | Move to purchases |
| SMALL_WIZARD_PURCHASES | "done" | SMALL_WIZARD_CONFIRM | Show summary |
| SMALL_WIZARD_CONFIRM | 1 | MAIN_MENU | Send to CA |
| MEDIUM_CREDIT_CHECK | auto | MEDIUM_CREDIT_RESULT | Run 2B + reconcile |
| MEDIUM_CREDIT_RESULT | 1 | GST_PERIOD_MENU | Continue filing |
| MEDIUM_CREDIT_RESULT | 2 | MEDIUM_CREDIT_RESULT | View mismatches |
| **Phase 8: Multi-GSTIN** | | | |
| MULTI_GSTIN_MENU | 1 | MULTI_GSTIN_ADD | Add GSTIN |
| MULTI_GSTIN_MENU | 3 | MULTI_GSTIN_SUMMARY | View summary |
| MULTI_GSTIN_ADD | valid GSTIN | MULTI_GSTIN_LABEL | Enter label |
| MULTI_GSTIN_LABEL | text | MULTI_GSTIN_MENU | Save + return |
| **Phase 9: Refund & Notice** | | | |
| REFUND_MENU | 1 | REFUND_TYPE | Select refund type |
| REFUND_TYPE | 1/2/3 | REFUND_DETAILS | Enter amount |
| REFUND_DETAILS | amount | MAIN_MENU | Create claim |
| NOTICE_MENU | 1 | NOTICE_MENU | List notices |
| NOTICE_MENU | 2 | NOTICE_UPLOAD | Upload notice |
| **Phase 10: Notifications** | | | |
| NOTIFICATION_SETTINGS | 1-5 | SETTINGS_MENU | Save preferences |

---

## 20. Upload Security Pipeline

```mermaid
flowchart TD
    UPLOAD["User uploads file<br/>(image/PDF/Excel)"] --> EMPTY{"Empty<br/>payload?"}
    EMPTY -->|yes| REJECT1["❌ Rejected:<br/>Empty file"]
    EMPTY -->|no| FNAME{"Filename<br/>safe?"}

    FNAME -->|path traversal/null bytes| REJECT2["❌ Rejected:<br/>Unsafe filename"]
    FNAME -->|safe| MIME{"MIME type<br/>allowed?"}

    MIME -->|not in allowlist| REJECT3["❌ Rejected:<br/>Invalid file type"]
    MIME -->|allowed| SIZE{"File size<br/>within limit?"}

    SIZE -->|>10MB image / >25MB PDF| REJECT4["❌ Rejected:<br/>File too large"]
    SIZE -->|ok| MAGIC{"Magic bytes<br/>match MIME?"}

    MAGIC -->|mismatch| REJECT5["❌ Rejected:<br/>File disguised"]
    MAGIC -->|match| PDF_CHECK{"Is PDF?"}

    PDF_CHECK -->|no| PASS["✅ Safe to process"]
    PDF_CHECK -->|yes| MALWARE{"Scan for<br/>malware patterns"}

    MALWARE -->|/JavaScript /Launch etc.| REJECT6["❌ Rejected:<br/>Suspicious PDF"]
    MALWARE -->|clean| PASS

    style PASS fill:#4CAF50,color:#fff
    style REJECT1 fill:#F44336,color:#fff
    style REJECT2 fill:#F44336,color:#fff
    style REJECT3 fill:#F44336,color:#fff
    style REJECT4 fill:#F44336,color:#fff
    style REJECT5 fill:#F44336,color:#fff
    style REJECT6 fill:#F44336,color:#fff
```

---

## 21. PII Masking Flow

```mermaid
flowchart LR
    INPUT["Raw text with<br/>sensitive data"] --> GSTIN_MASK["Mask GSTINs<br/>36AABCU9603R1ZM<br/>→ 36**********1ZM"]
    GSTIN_MASK --> PAN_MASK["Mask PANs<br/>AABCU9603R<br/>→ AA*****03R"]
    PAN_MASK --> PHONE_MASK["Mask phones<br/>+919876543210<br/>→ +91*****3210"]
    PHONE_MASK --> BANK_MASK["Mask bank accts<br/>1234567890<br/>→ ******7890"]
    BANK_MASK --> OUTPUT["Safe text<br/>for logs"]

    style INPUT fill:#F44336,color:#fff
    style OUTPUT fill:#4CAF50,color:#fff
```

---

## 22. Books vs Portal Comparison

```mermaid
flowchart TD
    subgraph "Data Sources"
        BOOKS["Accounting Books<br/>(User invoices in DB)"]
        PORTAL["GST Portal<br/>(GSTR-1 / GSTR-2B)"]
    end

    BOOKS --> COMPARE{"Compare with<br/>₹1 tolerance"}
    PORTAL --> COMPARE

    COMPARE --> MATCHED["✅ Matched<br/>(within tolerance)"]
    COMPARE --> VALUE["⚠️ Value Mismatch<br/>(amounts differ)"]
    COMPARE --> MISS_PORTAL["📤 Missing in Portal<br/>(in books, not filed)"]
    COMPARE --> MISS_BOOKS["📥 Missing in Books<br/>(in portal, not recorded)"]

    MATCHED --> SUMMARY["Comparison Summary<br/>matched/mismatched/missing<br/>counts + totals"]
    VALUE --> SUMMARY
    MISS_PORTAL --> SUMMARY
    MISS_BOOKS --> SUMMARY

    SUMMARY --> WA["WhatsApp<br/>formatted report"]
    SUMMARY --> API["REST API<br/>JSON response"]

    style MATCHED fill:#4CAF50,color:#fff
    style VALUE fill:#FF9800,color:#fff
    style MISS_PORTAL fill:#F44336,color:#fff
    style MISS_BOOKS fill:#9C27B0,color:#fff
```

---

## 23. Pending ITC Lifecycle

```mermaid
flowchart TD
    IMPORT["GSTR-2B Import<br/>(JSON/Excel/PDF)"] --> RECON["Invoice Reconciliation<br/>Books vs 2B"]

    RECON --> MATCHED["✅ Matched<br/>ITC available"]
    RECON --> UNMATCHED["⚠️ Unmatched<br/>Missing in 2B"]

    UNMATCHED --> PENDING["Pending ITC Bucket<br/>Track per period"]

    PENDING --> AGE{"Age of<br/>pending ITC"}
    AGE -->|"1 period"| BUCKET1["🟢 Recent<br/>(1 period)"]
    AGE -->|"2-3 periods"| BUCKET2["🟡 Aging<br/>(2-3 periods)"]
    AGE -->|"4+ periods"| BUCKET3["🔴 Critical<br/>(4+ periods)"]

    BUCKET1 --> FOLLOWUP["Generate vendor<br/>follow-up message"]
    BUCKET2 --> FOLLOWUP
    BUCKET3 --> FOLLOWUP

    FOLLOWUP --> WA["Send via WhatsApp<br/>to supplier"]

    PENDING --> CARRY["Carry forward<br/>to next period"]
    CARRY --> PENDING

    style MATCHED fill:#4CAF50,color:#fff
    style UNMATCHED fill:#FF9800,color:#fff
    style BUCKET3 fill:#F44336,color:#fff
```

---

## 24. Audit Trail Flow

```mermaid
flowchart TD
    ACTION["Admin/CA accesses<br/>client data"] --> LOG["log_access()<br/>actor, action, resource"]

    LOG --> BUFFER["In-memory ring buffer<br/>(max 10,000 entries)"]
    LOG --> STRUCT["Structured log file<br/>(persistent)"]

    BUFFER --> API_RECENT["GET /api/v1/audit/recent<br/>Filtered by actor/action/GSTIN"]
    BUFFER --> API_CLIENT["GET /api/v1/audit/client/{gstin}<br/>Access summary per actor"]

    style LOG fill:#2196F3,color:#fff
    style BUFFER fill:#FF9800,color:#fff
    style STRUCT fill:#4CAF50,color:#fff
```

---

## 25. Global Commands Flow

```mermaid
flowchart TD
    MSG["Incoming WhatsApp<br/>message"] --> G0{"Text is<br/>'0'?"}
    G0 -->|yes| MAIN["→ MAIN_MENU"]
    G0 -->|no| G9{"Text is<br/>'9'?"}

    G9 -->|yes| BACK["→ Pop stack<br/>(go back)"]
    G9 -->|no| NIL{"Text is<br/>'NIL'?"}

    NIL -->|yes| NILF["→ NIL_FILING_MENU"]
    NIL -->|no| HELP{"Text is<br/>'help' or '?'?"}

    HELP -->|yes| HELP_MSG["Show command<br/>reference card"]
    HELP -->|no| RESTART{"Text is<br/>'restart'?"}

    RESTART -->|yes| RESET["Clear session<br/>→ MAIN_MENU"]
    RESTART -->|no| CA{"Text is<br/>'ca'?"}

    CA -->|yes| HANDOFF["CA handoff<br/>acknowledgment"]
    CA -->|no| STATE["Continue to<br/>state machine"]

    style MAIN fill:#2196F3,color:#fff
    style HELP_MSG fill:#4CAF50,color:#fff
    style RESET fill:#FF9800,color:#fff
    style HANDOFF fill:#9C27B0,color:#fff
```

---

## 26. GSTR-2B Multi-Format Import

```mermaid
flowchart TD
    subgraph "Input Formats"
        JSON["JSON<br/>(GST Portal API)"]
        EXCEL["Excel .xlsx<br/>(Downloaded file)"]
        PDF["PDF<br/>(Scanned/downloaded)"]
    end

    JSON --> PARSE_JSON["Direct JSON parsing<br/>import_gstr2b()"]
    EXCEL --> PARSE_EXCEL["openpyxl parsing<br/>import_gstr2b_from_excel()"]
    PDF --> PARSE_PDF["pdfplumber + regex<br/>import_gstr2b_from_pdf()"]

    PARSE_JSON --> STORE["Store as<br/>Gstr2bInvoice records"]
    PARSE_EXCEL --> STORE
    PARSE_PDF --> STORE

    STORE --> RECON["Run reconciliation<br/>against books"]
    RECON --> ITC["Update ITC<br/>match status"]

    style JSON fill:#4CAF50,color:#fff
    style EXCEL fill:#2196F3,color:#fff
    style PDF fill:#FF9800,color:#fff
```
