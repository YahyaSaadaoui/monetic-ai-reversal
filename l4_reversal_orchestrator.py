import os, json, sqlite3, yaml, requests, xmltodict
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, condecimal

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools import tool

load_dotenv()

# ---------- Config ----------
DB_PATH = os.getenv("DB_PATH", "./reversal_audit.db")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
MODEL_ID = os.getenv("MODEL_ID", "gemini-1.5-flash")

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, ISO_FMT).replace(tzinfo=timezone.utc)

# ---------- Schema ----------
class Auth(BaseModel):
    auth_id: str
    card: str
    amount: condecimal(gt=0)
    currency: str
    merchant_id: str
    auth_time: str

class State(BaseModel):
    captured_amount: condecimal(ge=0) = 0
    voided: bool = False
    expiry_minutes: Optional[int] = None

class ReversalRequest(BaseModel):
    request_id: str
    type: Literal["full","partial"]
    request_time: str
    reason: str

class ReversalCase(BaseModel):
    auth: Auth
    state: State
    reversal_request: ReversalRequest
# --- Pure implementations (no decorators) ---
def load_rules_impl(path: str = "config/rules.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_case_impl(path: str) -> dict:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".xml":
        data = xmltodict.parse(raw)
        c = data["case"]
        return {
            "auth": {
                "auth_id": c["auth"]["auth_id"],
                "card": c["auth"]["card"],
                "amount": float(c["auth"]["amount"]),
                "currency": c["auth"]["currency"],
                "merchant_id": c["auth"]["merchant_id"],
                "auth_time": c["auth"]["auth_time"],
            },
            "state": {
                "captured_amount": float(c["state"]["captured_amount"]),
                "voided": str(c["state"]["voided"]).lower() == "true",
                "expiry_minutes": int(c["state"]["expiry_minutes"]),
            },
            "reversal_request": {
                "request_id": c["reversal_request"]["request_id"],
                "type": c["reversal_request"]["type"],
                "request_time": c["reversal_request"]["request_time"],
                "reason": c["reversal_request"]["reason"],
            }
        }
    return json.loads(raw)

def validate_case_impl(case: dict) -> str:
    try:
        ReversalCase(**case)
        return "valid"
    except ValidationError as e:
        return f"invalid: {e}"

def evaluate_eligibility_impl(case: dict, rules: dict) -> dict:
    rc = ReversalCase(**case)
    authorized = float(rc.auth.amount)
    captured = float(rc.state.captured_amount)
    voided = rc.state.voided
    expiry_minutes = rc.state.expiry_minutes or int(rules.get("expiry_minutes_default", 60))

    auth_time = parse_ts(rc.auth.auth_time)
    req_time = parse_ts(rc.reversal_request.request_time)
    elapsed_min = (req_time - auth_time).total_seconds() / 60.0

    decision = {
        "eligible": False,
        "mode": "none",
        "reversible_amount": 0.0,
        "actions": [],
        "notes": "",
        "meta": {
            "auth_id": rc.auth.auth_id,
            "request_id": rc.reversal_request.request_id,
            "merchant_id": rc.auth.merchant_id,
            "currency": rc.auth.currency
        }
    }

    if voided:
        decision["notes"] = "Authorization already voided."
        return decision

    if elapsed_min > expiry_minutes:
        decision["notes"] = f"Expired window: {elapsed_min:.1f} min > {expiry_minutes} min."
        return decision

    available = max(0.0, authorized - captured)
    if available <= 0:
        decision["notes"] = f"No funds on hold. Captured={captured:.2f} >= Authorized={authorized:.2f}."
        return decision

    if captured > 0:
        decision["eligible"] = True
        decision["mode"] = "partial"
        decision["reversible_amount"] = round(available, 2)
        decision["actions"] = [
            f"Release hold: {available:.2f} {rc.auth.currency} to card",
            f"Record reversal {rc.reversal_request.request_id} linked to {rc.auth.auth_id}",
            f"Notify merchant {rc.auth.merchant_id}"
        ]
        decision["notes"] = f"Captured {captured:.2f}, so only {available:.2f} remains reversible."
        return decision

    decision["eligible"] = True
    decision["mode"] = "full"
    decision["reversible_amount"] = round(available, 2)
    decision["actions"] = [
        f"Release hold: {available:.2f} {rc.auth.currency} to card",
        f"Record reversal {rc.reversal_request.request_id} linked to {rc.auth.auth_id}",
        f"Notify merchant {rc.auth.merchant_id}"
    ]
    decision["notes"] = "No capture yet; full amount is on hold."
    return decision

def ledger_plan_impl(decision: dict) -> dict:
    ops = []
    if decision.get("eligible"):
        amt = decision["reversible_amount"]
        cur = decision["meta"]["currency"]
        ops.append({"op":"RELEASE_HOLD","amount":amt,"currency":cur})
        ops.append({"op":"RECORD_REVERSAL","ref":decision["meta"]["request_id"],"auth":decision["meta"]["auth_id"]})
        ops.append({"op":"NOTIFY_MERCHANT","merchant_id":decision["meta"]["merchant_id"]})
    return {"ops": ops}

def audit_write_impl(decision: dict, ops: dict, db_path: str = DB_PATH) -> str:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS reversal_audit (
        ts TEXT, auth_id TEXT, request_id TEXT, merchant_id TEXT,
        eligible INTEGER, mode TEXT, reversible_amount REAL, notes TEXT, ops_json TEXT
    )""")
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("""INSERT INTO reversal_audit VALUES (?,?,?,?,?,?,?,?,?)""", (
        now,
        decision["meta"]["auth_id"],
        decision["meta"]["request_id"],
        decision["meta"]["merchant_id"],
        1 if decision["eligible"] else 0,
        decision["mode"],
        decision["reversible_amount"],
        decision["notes"],
        json.dumps(ops["ops"])
    ))
    conn.commit()
    conn.close()
    return "audit_ok"

def notify_webhook_impl(decision: dict, ops: dict, webhook_url: str = WEBHOOK_URL) -> str:
    if not webhook_url:
        return "skipped (no WEBHOOK_URL)"
    payload = {"title": "Reversal Decision", "decision": decision, "ops": ops}
    try:
        r = requests.post(webhook_url, json=payload, timeout=5)
        return f"webhook_status={r.status_code}"
    except Exception as e:
        return f"webhook_error={str(e)}"
@tool(show_result=True)
def load_rules(path: str = "config/rules.yaml") -> dict:
    return load_rules_impl(path)

@tool(show_result=True)
def load_case(path: str) -> dict:
    return load_case_impl(path)

@tool(show_result=True)
def validate_case(case: dict) -> str:
    return validate_case_impl(case)

@tool(show_result=True)
def evaluate_eligibility(case: dict, rules: dict) -> dict:
    return evaluate_eligibility_impl(case, rules)

@tool(show_result=True)
def ledger_plan(decision: dict) -> dict:
    return ledger_plan_impl(decision)

@tool(show_result=True)
def audit_write(decision: dict, ops: dict, db_path: str = DB_PATH) -> str:
    return audit_write_impl(decision, ops, db_path)

@tool(show_result=True)
def notify_webhook(decision: dict, ops: dict, webhook_url: str = WEBHOOK_URL) -> str:
    return notify_webhook_impl(decision, ops, webhook_url)
# ---------- Tools (Level-4 steps) ----------
@tool(show_result=True)
def load_rules(path: str = "config/rules.yaml") -> dict:
    """Load YAML rules (expiry default, tolerance)"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

@tool(show_result=True)
def load_case(path: str) -> dict:
    """Load case from JSON or XML file"""
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".xml":
        data = xmltodict.parse(raw)
        # normalize XML to dict similar to JSON shape
        c = data["case"]
        return {
            "auth": {
                "auth_id": c["auth"]["auth_id"],
                "card": c["auth"]["card"],
                "amount": float(c["auth"]["amount"]),
                "currency": c["auth"]["currency"],
                "merchant_id": c["auth"]["merchant_id"],
                "auth_time": c["auth"]["auth_time"],
            },
            "state": {
                "captured_amount": float(c["state"]["captured_amount"]),
                "voided": str(c["state"]["voided"]).lower() == "true",
                "expiry_minutes": int(c["state"]["expiry_minutes"]),
            },
            "reversal_request": {
                "request_id": c["reversal_request"]["request_id"],
                "type": c["reversal_request"]["type"],
                "request_time": c["reversal_request"]["request_time"],
                "reason": c["reversal_request"]["reason"],
            }
        }
    else:
        return json.loads(raw)

@tool(show_result=True)
def validate_case(case: dict) -> str:
    """Validate case schema with pydantic (raises on error)"""
    try:
        ReversalCase(**case)
        return "valid"
    except ValidationError as e:
        return f"invalid: {e}"

@tool(show_result=True)
def evaluate_eligibility(case: dict, rules: dict) -> dict:
    """Apply reversal rules and compute decision"""
    rc = ReversalCase(**case)  # will raise if invalid
    authorized = float(rc.auth.amount)
    captured = float(rc.state.captured_amount)
    voided = rc.state.voided
    expiry_minutes = rc.state.expiry_minutes or int(rules.get("expiry_minutes_default", 60))

    auth_time = parse_ts(rc.auth.auth_time)
    req_time = parse_ts(rc.reversal_request.request_time)
    elapsed_min = (req_time - auth_time).total_seconds() / 60.0

    decision = {
        "eligible": False,
        "mode": "none",
        "reversible_amount": 0.0,
        "actions": [],
        "notes": "",
        "meta": {
            "auth_id": rc.auth.auth_id,
            "request_id": rc.reversal_request.request_id,
            "merchant_id": rc.auth.merchant_id,
            "currency": rc.auth.currency
        }
    }

    if voided:
        decision["notes"] = "Authorization already voided."
        return decision

    if elapsed_min > expiry_minutes:
        decision["notes"] = f"Expired window: {elapsed_min:.1f} min > {expiry_minutes} min."
        return decision

    available = max(0.0, authorized - captured)
    if available <= 0:
        decision["notes"] = f"No funds on hold. Captured={captured:.2f} >= Authorized={authorized:.2f}."
        return decision

    if captured > 0:
        decision["eligible"] = True
        decision["mode"] = "partial"
        decision["reversible_amount"] = round(available, 2)
        decision["actions"] = [
            f"Release hold: {available:.2f} {rc.auth.currency} to card",
            f"Record reversal {rc.reversal_request.request_id} linked to {rc.auth.auth_id}",
            f"Notify merchant {rc.auth.merchant_id}"
        ]
        decision["notes"] = f"Captured {captured:.2f}, so only {available:.2f} remains reversible."
        return decision

    decision["eligible"] = True
    decision["mode"] = "full"
    decision["reversible_amount"] = round(available, 2)
    decision["actions"] = [
        f"Release hold: {available:.2f} {rc.auth.currency} to card",
        f"Record reversal {rc.reversal_request.request_id} linked to {rc.auth.auth_id}",
        f"Notify merchant {rc.auth.merchant_id}"
    ]
    decision["notes"] = "No capture yet; full amount is on hold."
    return decision

@tool(show_result=True)
def ledger_plan(decision: dict) -> dict:
    """Convert decision into atomic ledger ops"""
    ops = []
    if decision.get("eligible"):
        amt = decision["reversible_amount"]
        cur = decision["meta"]["currency"]
        ops.append({"op":"RELEASE_HOLD","amount":amt,"currency":cur})
        ops.append({"op":"RECORD_REVERSAL","ref":decision["meta"]["request_id"],"auth":decision["meta"]["auth_id"]})
        ops.append({"op":"NOTIFY_MERCHANT","merchant_id":decision["meta"]["merchant_id"]})
    return {"ops": ops}

@tool(show_result=True)
def audit_write(decision: dict, ops: dict, db_path: str = DB_PATH) -> str:
    """Write an audit record to SQLite"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS reversal_audit (
        ts TEXT, auth_id TEXT, request_id TEXT, merchant_id TEXT,
        eligible INTEGER, mode TEXT, reversible_amount REAL, notes TEXT, ops_json TEXT
    )""")
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    cur.execute("""INSERT INTO reversal_audit VALUES (?,?,?,?,?,?,?,?,?)""", (
        now,
        decision["meta"]["auth_id"],
        decision["meta"]["request_id"],
        decision["meta"]["merchant_id"],
        1 if decision["eligible"] else 0,
        decision["mode"],
        decision["reversible_amount"],
        decision["notes"],
        json.dumps(ops["ops"])
    ))
    conn.commit()
    conn.close()
    return "audit_ok"

@tool(show_result=True)
def notify_webhook(decision: dict, ops: dict, webhook_url: str = WEBHOOK_URL) -> str:
    """POST decision to a webhook (Slack/Discord/custom). No-op if no URL."""
    if not webhook_url:
        return "skipped (no WEBHOOK_URL)"
    payload = {
        "title": "Reversal Decision",
        "decision": decision,
        "ops": ops
    }
    try:
        r = requests.post(webhook_url, json=payload, timeout=5)
        return f"webhook_status={r.status_code}"
    except Exception as e:
        return f"webhook_error={str(e)}"

# ---------- Agents ----------
planner = Agent(
    name="Planner",
    role="Plan and call tools...",
    model=Gemini(id=MODEL_ID),
    tools=[load_rules, load_case, validate_case, evaluate_eligibility, ledger_plan, audit_write, notify_webhook],
    reasoning=True,
    markdown=True,
)


reporter = Agent(
    name="Reporter",
    role="Summarize the final decision and ops for humans in Markdown; keep it short and clear.",
    model=Gemini(id=MODEL_ID),
    reasoning=False,
    markdown=True,
)

def run_pipeline(case_path: str) -> dict:
    rules = load_rules_impl("config/rules.yaml")
    case = load_case_impl(case_path)
    if "invalid:" in validate_case_impl(case):
        raise ValueError("Invalid input case.")
    decision = evaluate_eligibility_impl(case, rules)
    ops = ledger_plan_impl(decision)
    audit_write_impl(decision, ops, DB_PATH)
    notify_webhook_impl(decision, ops, WEBHOOK_URL)
    return {"decision": decision, "ops": ops}


if __name__ == "__main__":
    import sys
    case_path = sys.argv[1] if len(sys.argv) > 1 else "data/reversal_ok.json"

    # Try L4 “Planner + tools” path; if quota hits, fall back to local deterministic pipeline.
    try:
        print("\n--- Level 4 (Planner orchestrates tools) ---\n")
        planner.print_response(
            f"Load rules from config/rules.yaml, load case from {Path(case_path).resolve().as_posix()}, "
            "validate it, evaluate eligibility, build ledger plan, audit to DB, and notify webhook. "
            "Finally, return the JSON decision and ops.",
            stream=True
        )
    except Exception as e:
        print(f"\n[L4 planner fallback] {e}\n")

    # Always produce a final deterministic output and a short report
    result = run_pipeline(case_path)
    final_json = json.dumps(result, indent=2)
    print("\n--- Deterministic Output ---\n")
    print(final_json)

    try:
        print("\n--- Reporter (LLM summary, optional) ---\n")
        reporter.print_response(
            f"Summarize in one paragraph for a product manager:\n{final_json}",
            stream=True
        )
    except Exception as e:
        print(f"[Reporter fallback] {e}\n")
        # Minimal local summary
        d = result["decision"]
        verdict = "approved" if d["eligible"] else "denied"
        print(f"Summary: Reversal {verdict} ({d['mode']}). Amount={d['reversible_amount']} {d['meta']['currency']}. Notes: {d['notes']}")
