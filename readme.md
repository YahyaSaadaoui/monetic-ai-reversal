# Level-4 Reversal Orchestrator

A **Level-4 monétique reversal orchestrator** built with [Agno](https://docs.agno.com/) agents and deterministic Python business logic.
It evaluates reversal requests (full or partial) based on authorization state, generates atomic ledger operations, writes an audit trail, optionally posts to a webhook, and produces a human-friendly summary.

---

## Features

- **Deterministic core logic** — Always works, even with no LLM quota.
- **Level-4 multi-agent orchestration**:
  - **Planner Agent** — Orchestrates the workflow by calling registered tools in the correct order.
  - **Reporter Agent** — Summarizes the final decision for stakeholders.
- **Pydantic validation** for inputs.
- **YAML-based rules** (expiry window, etc.).
- **Supports JSON & XML** input formats.
- **SQLite audit log** of all reversal decisions.
- **Optional webhook** notification.
- **Gemini model integration** (via Agno) for planning and summaries.

---

## Requirements

- Python 3.9+
- [Google Gemini API key](https://aistudio.google.com/) (optional — required only for LLM planning/summaries)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/reversal-orchestrator.git
cd reversal-orchestrator
2. Create and activate a virtual environment (recommended)
bash
Copier
Modifier
python -m venv agnoenv
# Windows
agnoenv\Scripts\activate
# Mac/Linux
source agnoenv/bin/activate
(You can run without a venv, but it’s strongly recommended to avoid dependency conflicts.)

3. Install dependencies
bash
Copier
Modifier
pip install -r requirements.txt
Configuration
Create a .env file in the project root:

env
Copier
Modifier
GOOGLE_API_KEY=your_gemini_api_key_here   # Optional, for LLM planning & summaries
WEBHOOK_URL=                               # Optional, for posting results
DB_PATH=./reversal_audit.db
MODEL_ID=gemini-1.5-flash                  # or gemini-1.5-pro
Review config/rules.yaml to adjust policy settings:

yaml
Copier
Modifier
expiry_minutes_default: 60
amount_tolerance: 0.01
Usage
Run with JSON input
bash
Copier
Modifier
python l4_reversal_orchestrator.py data/reversal_ok.json
Run with XML input
bash
Copier
Modifier
python l4_reversal_orchestrator.py data/reversal_ok.xml
Sample Output
When run with data/reversal_ok.json:

bash
Copier
Modifier
=== Level-4 Planner (Agno Agent) ===
[Tool call logs & reasoning here]

=== Deterministic Output ===
{
  "decision": {
    "eligible": true,
    "mode": "partial",
    "reversible_amount": 80.0,
    "actions": ["RELEASE_HOLD", "RECORD_REVERSAL", "NOTIFY_MERCHANT"],
    "notes": "Partial reversal; release remaining hold.",
    "meta": {...}
  },
  "ops": [
    {"op": "RELEASE_HOLD", "amount": 80.0},
    {"op": "RECORD_REVERSAL", "amount": 80.0},
    {"op": "NOTIFY_MERCHANT", "merchant_id": "M01"}
  ]
}

=== Human Summary ===
Partial reversal approved: releasing $80.00 USD hold for merchant M01.
Project Structure
pgsql
Copier
Modifier
.
├── config/
│   └── rules.yaml              # Policy rules
├── data/                       # Sample case files
│   ├── reversal_ok.json
│   ├── reversal_expired.json
│   └── reversal_ok.xml
├── l4_reversal_orchestrator.py # Main orchestrator script
├── requirements.txt
├── .env.example
└── README.md
Extending the Project
Add new rules to config/rules.yaml.

Create new tool wrappers to integrate with external services (e.g., payment gateways, messaging systems).

Implement batch processing for multiple case files.

Wrap in a FastAPI or Flask service for HTTP API access.
```
