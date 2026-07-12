# Mapfl0w — Agentic STTM Automation

Mapfl0w automates Source-to-Target Mapping (STTM) — a manual, error-prone process where data engineers translate mapping spreadsheets into transformation code. At companies like Saama Technologies, this typically requires multiple engineers spending days writing Dataform `.sqlx` files by hand from Google Sheets templates.

Mapfl0w replaces that process with an LLM agent that reads your mapping documents, generates validated transformation code, self-corrects against a real database dry-run, and executes the transformation after human review.

---

## How it works

```
You upload 5 files
        │
        ▼
┌─────────────────────────────────────────────────────┐
│                  LangGraph Agent                     │
│                                                     │
│  parse ──► validate ──► generate ──► dry-run        │
│                              ▲           │          │
│                              └── retry ──┘          │
│                           (max 3 attempts)          │
│                                   │                 │
│                            interrupt()              │
└───────────────────────────────────┼─────────────────┘
                                    │
                          Human review in UI
                                    │
                               Approve
                                    │
                    push .sqlx ──► execute ──► audit
```

The agent is genuinely agentic in three ways:

**1. Adaptive planning** — the LLM decides what to call next based on what it observes, not a hardcoded sequence. If it encounters an unexpected lookup dependency it wasn't told about, it handles it.

**2. Self-correction loop** — when the dry-run fails, the LLM reads the exact error, reasons about the cause, and regenerates. This is not retry logic — it's the agent debugging its own output.

**3. Judgment-based escalation** — validator ERRORs stop generation entirely. Three consecutive dry-run failures escalate to the human with a full explanation. The agent knows when to ask rather than guess.

---

## The 5 input files

| File | Format | Purpose |
|---|---|---|
| Source schema | `.md` | Column definitions for your source table |
| Target schema | `.md` | Column definitions for your target table |
| STTM sheet | `.csv` or `.xlsx` | The mapping: source → transformation → target |
| Repo structure | `.md` | Folder conventions, naming, config defaults |
| UDF definitions | `.md` (optional) | Your team's custom functions |

Sample files for a clinical data use case are in `backend/sample_inputs/`.

---

## Tech stack

```
Frontend    React + Vite + TanStack Router + shadcn/ui
Backend     FastAPI + LangGraph + Groq (llama-3.3-70b) + LangSmith
Database    PostgreSQL (run history + demo data)
Tools       Postgres EXPLAIN (dry-run) · GitHub API (code push) · SQLAlchemy
```

---

## Project structure

```
mapflow/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   │   ├── graph.py        # LangGraph state machine (generation + execution graphs)
│   │   │   └── prompts.py      # LLM system prompt + generation/correction templates
│   │   ├── api/
│   │   │   └── runs.py         # FastAPI endpoints: POST /runs, GET /runs/{id}, approve, reject
│   │   ├── tools/
│   │   │   ├── parsers.py      # MD schema parser + STTM CSV/Excel parser
│   │   │   ├── validator.py    # Deterministic validator (existence, types, nullability, duplicates)
│   │   │   ├── postgres_tools.py  # Schema fetch, EXPLAIN dry-run, execute, audit
│   │   │   ├── github_tools.py    # Push .sqlx to GitHub via contents API
│   │   │   └── sqlx.py         # Extract SELECT from .sqlx, resolve ${ref()}, build INSERT
│   │   ├── services/
│   │   │   └── runstore.py     # Thread-safe run state updates (agent writes from background thread)
│   │   ├── config.py           # Settings via pydantic-settings + .env
│   │   ├── database.py         # SQLAlchemy models (RunRecord)
│   │   ├── main.py             # FastAPI app + CORS + startup
│   │   └── schemas.py          # RunRecord → camelCase dict (matches frontend types.ts)
│   ├── sample_inputs/          # Working demo: clinical_patients source → target
│   ├── seed/seed.sql           # Creates raw.clinical_patients (10 rows) + analytics.fct_clinical_patients
│   ├── test_e2e.py             # End-to-end test with stubbed LLM (proves retry loop + audit)
│   ├── docker-compose.yml      # Postgres on port 5433
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── routes/             # One file per page (TanStack file-based routing)
    │   │   ├── index.tsx           # Runs dashboard
    │   │   ├── new-run.tsx         # 5-file upload
    │   │   ├── runs.$runId.index.tsx   # Run status + agent activity feed
    │   │   ├── runs.$runId.review.tsx  # Human review gate
    │   │   └── runs.$runId.result.tsx  # Run result + audit
    │   ├── components/
    │   │   ├── ActivityFeed.tsx    # Terminal-style agent reasoning stream
    │   │   ├── Stepper.tsx         # 8-step pipeline progress
    │   │   ├── AppShell.tsx        # Sidebar + layout
    │   │   └── CodeBlock.tsx       # .sqlx syntax display
    │   └── lib/
    │       ├── api.ts          # HTTP client (polling GET /runs/{id} every 1.2s)
    │       └── types.ts        # Run type + STEP_LABELS
    └── vite.config.ts
```

---

## Prerequisites

- Docker Desktop
- Python 3.11+ (3.13 works)
- Node 20+
- A free Groq API key — https://console.groq.com
- (Optional) LangSmith API key — https://smith.langchain.com
- (Optional) GitHub fine-grained PAT for `.sqlx` push

---

## Setup

### 1. Start Postgres

```bash
cd backend
docker compose up -d
```

Verify seed data loaded (should return 10):

```bash
# Windows
docker exec -it backend-db-1 psql -U mapflow -d mapflow -c "SELECT COUNT(*) FROM raw.clinical_patients;"

# Mac/Linux
docker exec -it $(docker ps -qf "name=mapflow") psql -U mapflow -d mapflow -c "SELECT COUNT(*) FROM raw.clinical_patients;"
```

### 2. Configure backend

```bash
cd backend
cp .env.example .env
```

Open `.env` and set at minimum:

```env
GROQ_API_KEY=gsk_your_key_here
```

Optional — add these for GitHub push and LangSmith tracing:

```env
GITHUB_TOKEN=github_pat_your_token_here
GITHUB_REPO=your-username/dataform-models
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_your_key_here
```

If `GITHUB_TOKEN` is left empty, the push step is skipped gracefully — everything else still works.

### 3. Run the backend

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Mac/Linux
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Verify: `curl localhost:8000/health` should return `{"ok":true}`

### 4. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:8080

---

## Running your first job

1. Open http://localhost:8080 → click **New Run**
2. Upload the 5 files from `backend/sample_inputs/`
   - `source_schema.md` → Source schema
   - `target_schema.md` → Target schema
   - `sttm.csv` or `sttm.xlsx` → STTM sheet (both formats supported)
   - `repo_structure.md` → Repo structure
   - `udf_definitions.md` → UDF definitions
3. Click **Start Run** and watch the Agent Activity Feed
4. When the pipeline pauses at **Human review** → click **Review now**
5. Read the generated `.sqlx` and findings panel → click **Approve & execute**
6. Watch execution and audit complete

Verify data landed:

```bash
docker exec -it backend-db-1 psql -U mapflow -d mapflow \
  -c "SELECT patient_id, full_name, email_address, site_city FROM analytics.fct_clinical_patients LIMIT 5;"
```

---
