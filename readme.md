# Agno Agentics Reversal Eligibility Demo

Lightweight, end-to-end demo that evaluates **card authorization reversal** eligibility from uploaded case files and shows a **human-readable summary** in a Next.js UI.

The stack:

* **Python / FastAPI** service (Agno Playground app)
* **Next.js 15** front-end (Agent UI)
* Deterministic pipeline (no LLM required) with optional Gemini agent(s) for extras
* Single-file mode: JSON / XML / CSV
* **Batch mode**: ZIP **and RAR** (unzipped server-side)

## What it does

* Parse a case (auth + state + reversal request)
* Resolve rules (global + merchant override)
* Validate, evaluate eligibility, compute reversible amount
* Produce ledger ops plan
* Persist an audit row (SQLite)
* (Optional) call a webhook
* Return a **short human summary** to the UI
  `Reversal eligible (full). Amount 75 USD. Notes: No capture yet; full amount is on hold.`

## Features

* ✅ JSON / XML / CSV single files
* ✅ ZIP / RAR batch folders
* ✅ Human-readable summaries (no JSON echoed to the chat)
* ✅ SQLite audit trail (`reversal_audit.db`)
* ✅ Per-merchant rule overrides (`/rules/*.yaml`)
* ✅ CORS-safe upload endpoint
* ✅ “Thinking” loader and graceful error messages in the UI

## Repo layout

```
.
├── config/
│   └── rules.yaml                     # global defaults
├── rules/
│   ├── M01.yaml                       # merchant overrides (examples)
│   └── M09.yaml
├── data/                              # sample inputs
│   ├── reversal_case.json
│   ├── reversal_ok.xml
│   ├── reversal_expired.csv
│   ├── reversal_ok.zip                # batch
│   └── reversal_ok.rar                # batch
├── out/                               # generated summaries (batch)
├── ui/
│   └── agent-ui/                      # Next.js app
├── l4_reversal_orchestrator.py        # deterministic pipeline
├── ui_tools.py                        # upload + batch adapters (ZIP/RAR)
├── playground.py                      # FastAPI + /upload + agents
├── web_app.py                         # (optional) minimal HTML app
├── reversal_agent.py                  # (optional) agent entrypoint
├── requirements.txt
└── reversal_audit.db                  # created on first run
```

## Requirements

* Python 3.10+
* Node 18+ / PNPM or NPM
* **RAR support**: `unrar` binary available on your PATH
  * Windows: install WinRAR and add the install dir to PATH (or install `unrar` from chocolatey)
  * macOS: `brew install unrar`
  * Linux: `sudo apt-get install unrar` (or distro equivalent)

## Setup

### 1) Python backend

```bash
# create & activate venv (recommended)
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

Environment (optional):

```
# .env (repo root)
DB_PATH=./reversal_audit.db
WEBHOOK_URL=
MODEL_ID=gemini-1.5-flash
```

Run the playground API (serves Agno Playground + our custom routes):

```bash
python playground.py
```

You should see something like:

```
Agent Playground URL: https://app.agno.com/playground?endpoint=127.0.0.1%3A7777/v1
```

> Our upload route lives at **`POST /upload`** (no `/v1` prefix).
> The UI automatically points to that route by taking the endpoint’s **origin**.

### 2) Front-end UI (Next.js)

```bash
cd ui/agent-ui
# with pnpm
pnpm i
pnpm dev -p 3000
# or with npm
npm i
npm run dev -p 3000
```

Open: `http://localhost:3000`

* Set the **Endpoint** to `http://localhost:7777/v1` (green dot shows it’s reachable).
* Choose **Reversal Agent**.
* Click the download icon to **upload** a case file:
  * Single: `.json`, `.xml`, `.csv`
  * Batch: `.zip`, `.rar`

You’ll see:

1. “Uploaded file: …”
2. A thinking loader
3. A **short human summary** (no JSON blob)

## API contract

### `POST /upload` (multipart/form-data)

* **file**: single file (JSON/XML/CSV) or archive (ZIP/RAR)

**Response**

```json
{
  "ok": true,
  "summary": "Reversal eligible (full). Amount 75 USD. Notes: No capture yet; full amount is on hold."
}
```

> In batch mode (ZIP/RAR), the summary condenses totals:
> `Processed 10 cases. Eligible: 7 (full 4, partial 3). Ineligible: 3. By currency: USD: reversible total 180.0 over 6 cases; EUR: reversible total 40.0 over 1 cases`

## Case formats

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
  "state": { "captured_amount": 0, "voided": false, "expiry_minutes": 60 },
  "reversal_request": {
    "request_id": "R771",
    "type": "full",
    "request_time": "2025-08-16T20:40:00Z",
    "reason": "customer canceled"
  }
}
```

> The loader also accepts `{ "case": { ... } }` and unwraps it.

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

### CSV (first row used)

```
auth_id,card,amount,currency,merchant_id,auth_time,captured_amount,voided,expiry_minutes,request_id,type,request_time,reason
A777,**** **** **** 1234,75,USD,M77,2025-08-16T20:30:00Z,0,false,60,R771,full,2025-08-16T20:40:00Z,customer canceled
```

## Rules

* Global defaults: `config/rules.yaml`
* Merchant overrides: `rules/<merchant_id>.yaml` (merged over defaults)

## Outputs & persistence

* **SQLite**: `reversal_audit.db` (one row per processed case)
* **Batch**: `out/summary_*.json` and `out/summary_*.csv`

## CLI quick tests (optional)

Deterministic pipeline without the UI:

```bash
# single case
python l4_reversal_orchestrator.py data/reversal_ok.xml

# batch folder
python l4_reversal_orchestrator.py --batch data --out out
```

Local upload smoke test:

```bash
# with backend running on 127.0.0.1:7777
python - <<'PY'
import base64, requests
p = "data/reversal_ok.xml"
b64 = base64.b64encode(open(p,"rb").read())
files={"file": (p, open(p,"rb"), "application/xml")}
r = requests.post("http://127.0.0.1:7777/upload", files=files, timeout=20)
print(r.status_code, r.json())
PY
```

## Troubleshooting

* **RAR upload fails** → install `unrar` and ensure it’s on your PATH.
* **“Failed to fetch” in UI** → check backend is on `http://127.0.0.1:7777`, endpoint in UI is `http://localhost:7777/v1`, and CORS isn’t blocked.
* **Got JSON in chat** → backend now always returns a **plain sentence** via `summarize_result()`; make sure you’re on the latest `playground.py`.
* **Network changed / hot reload** → ignore transient Next.js hot-reload warnings.

## Notes

* This code is **demo-grade**: deterministic logic, explicit side-effects, tiny schema via Pydantic. Add auth, rate-limits, and input scanning before deploying anywhere sensitive.
* The Reporter/Planner agents are included; the upload path **does not require** an LLM.

## License

MIT (see `LICENSE`).
