# Agno Agentics Reversal Eligibility Demo

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![SQLite](https://img.shields.io/badge/SQLite-audit_trail-003B57?logo=sqlite&logoColor=white)](https://sqlite.org/)

A fintech-focused demo that evaluates card authorization reversal eligibility from uploaded case files and returns a concise operator-friendly decision in a Next.js UI.

It combines a deterministic Python/FastAPI pipeline with an optional Agno/Gemini agent layer. The core reversal logic works without an LLM, while the agent layer can help with orchestration and summaries.

## Why This Exists

In card payments, a reversal cancels all or part of a transaction authorization before it becomes a final financial mismatch.

Common examples:

- A customer cancels after authorization.
- A POS or ATM flow fails after funds were held.
- A partial capture leaves the remaining hold to release.
- A delayed reversal creates reconciliation or dispute work.

At scale, reversal handling becomes messy because rules can depend on merchant, network, authorization state, expiry windows, captured amounts, and operational exceptions.

This project models that workflow as a small, testable orchestrator:

- Receive case data as JSON, XML, CSV, ZIP, or RAR.
- Validate the authorization state and reversal request.
- Apply global and merchant-specific YAML rules.
- Decide whether the reversal is eligible, full, partial, or rejected.
- Generate ledger operation plans.
- Write an SQLite audit trail.
- Return a human-readable summary for operators.

## What It Does

- Parses single-case files and batch archives.
- Resolves policy rules from `config/rules.yaml` and `rules/<merchant_id>.yaml`.
- Computes reversible amounts based on captured amount, request type, expiry, and void state.
- Produces a ledger operation plan such as `RELEASE_HOLD`, `RECORD_REVERSAL`, and `NOTIFY_MERCHANT`.
- Stores decisions in `reversal_audit.db` for traceability.
- Exposes a FastAPI upload endpoint consumed by the Next.js UI.

Example operator summary:

> Reversal eligible (full). Amount 75 USD. Notes: No capture yet; full amount is on hold.

Batch summary example:

> Processed 10 cases. Eligible: 7 (full 4, partial 3). Ineligible: 3. By currency: USD: reversible total 180.0 over 6 cases; EUR: reversible total 40.0 over 1 case.

## Stack

| Layer | Technology |
| --- | --- |
| Backend | Python, FastAPI, Pydantic, SQLAlchemy, SQLite |
| Rules | YAML global defaults and merchant overrides |
| UI | Next.js 15, React 19, TypeScript, Tailwind |
| Agent layer | Agno with optional Gemini model integration |
| Inputs | JSON, XML, CSV, ZIP, RAR |

## Repository Layout

```text
.
├── config/
│   └── rules.yaml                  # global reversal policy defaults
├── rules/
│   ├── M01.yaml                    # merchant override examples
│   └── M09.yaml
├── data/                           # sample single and batch inputs
├── out/                            # generated batch summaries
├── ui/
│   └── agent-ui/                   # Next.js operator UI
├── l4_reversal_orchestrator.py     # deterministic pipeline
├── ui_tools.py                     # upload and batch adapters
├── playground.py                   # FastAPI app and Agno playground integration
├── requirements.txt
└── reversal_audit.db               # local audit DB generated during runs
```

## Requirements

- Python 3.10+
- Node.js 18+
- PNPM or NPM
- Optional: Gemini API key for Agno/Gemini summaries
- Optional for RAR batch input: `unrar` available on `PATH`

RAR support:

```bash
# Windows: install WinRAR and add it to PATH, or use Chocolatey
choco install unrar

# macOS
brew install unrar

# Linux
sudo apt-get install unrar
```

## Quick Start

### 1. Run the Python backend

```bash
git clone https://github.com/YahyaSaadaoui/monetic-ai-reversal.git
cd monetic-ai-reversal

python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
python playground.py
```

The API runs at:

```text
http://127.0.0.1:7777
```

The upload route is:

```text
POST /upload
```

### 2. Run the Next.js UI

```bash
cd ui/agent-ui
pnpm install
pnpm dev -p 3000
```

Or with npm:

```bash
cd ui/agent-ui
npm install
npm run dev -- -p 3000
```

Open:

```text
http://localhost:3000
```

Set the endpoint to:

```text
http://localhost:7777/v1
```

Then choose the reversal agent and upload a `.json`, `.xml`, `.csv`, `.zip`, or `.rar` case file.

## Environment

Create an optional `.env` file in the repository root:

```env
DB_PATH=./reversal_audit.db
WEBHOOK_URL=
MODEL_ID=gemini-1.5-flash
GOOGLE_API_KEY=
```

The deterministic business pipeline does not require an API key. The key is only needed if you want the optional Gemini-powered agent behavior.

## API Contract

### POST `/upload`

Request: `multipart/form-data`

| Field | Description |
| --- | --- |
| `file` | Single case file or ZIP/RAR archive |

Success response:

```json
{
  "ok": true,
  "summary": "Reversal eligible (full). Amount 75 USD. Notes: No capture yet; full amount is on hold."
}
```

## Input Examples

### JSON

```json
{
  "auth": {
    "auth_id": "A777",
    "card": "**** **** **** 1234",
    "amount": 75,
    "currency": "USD",
    "merchant_id": "M77",
    "auth_time": "2025-08-16T20:30:00Z"
  },
  "state": {
    "captured_amount": 0,
    "voided": false,
    "expiry_minutes": 60
  },
  "reversal_request": {
    "request_id": "R771",
    "type": "full",
    "request_time": "2025-08-16T20:40:00Z",
    "reason": "customer canceled"
  }
}
```

The loader also accepts:

```json
{ "case": { } }
```

and unwraps the nested case object.

### XML

```xml
<case>
  <auth>
    <auth_id>A777</auth_id>
    <card>**** **** **** 1234</card>
    <amount>75</amount>
    <currency>USD</currency>
    <merchant_id>M77</merchant_id>
    <auth_time>2025-08-16T20:30:00Z</auth_time>
  </auth>
  <state>
    <captured_amount>0</captured_amount>
    <voided>false</voided>
    <expiry_minutes>60</expiry_minutes>
  </state>
  <reversal_request>
    <request_id>R771</request_id>
    <type>full</type>
    <request_time>2025-08-16T20:40:00Z</request_time>
    <reason>customer canceled</reason>
  </reversal_request>
</case>
```

### CSV

```csv
auth_id,card,amount,currency,merchant_id,auth_time,captured_amount,voided,expiry_minutes,request_id,type,request_time,reason
A777,**** **** **** 1234,75,USD,M77,2025-08-16T20:30:00Z,0,false,60,R771,full,2025-08-16T20:40:00Z,customer canceled
```

## CLI Smoke Tests

Run the deterministic pipeline directly:

```bash
python l4_reversal_orchestrator.py data/reversal_ok.xml
python l4_reversal_orchestrator.py --batch data --out out
```

Test the upload endpoint while the backend is running:

```bash
python - <<'PY'
import requests

path = "data/reversal_ok.xml"
with open(path, "rb") as handle:
    files = {"file": (path, handle, "application/xml")}
    response = requests.post("http://127.0.0.1:7777/upload", files=files, timeout=20)

print(response.status_code)
print(response.json())
PY
```

## Good First Improvements

These are realistic contribution ideas for anyone who wants to extend the project:

- Add more test cases for partial reversal edge cases.
- Add Mastercard/Visa-style response-code examples.
- Add a small dashboard page for audit history from SQLite.
- Add unit tests around rule merging and amount calculation.
- Add screenshots or a GIF of the upload flow.
- Add Docker Compose for backend + frontend local startup.

## Notes

This is a learning/demo project. It is not connected to a live payment network and should not be used as production payment infrastructure without security review, operational hardening, audit controls, and real scheme compliance validation.

## License

Add a license before using this in a shared or commercial context.
