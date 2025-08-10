import sys
import os, json, sqlite3, yaml, requests, xmltodict
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Literal
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, condecimal
from csv import DictReader
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

def validate_case_impl(case: dict) -> str:
    try:
        ReversalCase(**case)
        return "valid"
    except ValidationError as e:
        return f"invalid: {e}"

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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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

def load_case_impl(path: str) -> dict:
    def _to_bool(x: str) -> bool:
        return str(x).strip().lower() in ("1", "true", "yes", "y")

    p = Path(path)
    raw = p.read_text(encoding="utf-8")

    # XML path
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

    # CSV path
    if p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8", newline="") as f:
            rows = list(DictReader(f))
        if not rows:
            raise ValueError("CSV file is empty")
        r = rows[0]  # one row = one case
        try:
            return {
                "auth": {
                    "auth_id": r["auth_id"],
                    "card": r["card"],
                    "amount": float(r["amount"]),
                    "currency": r["currency"],
                    "merchant_id": r["merchant_id"],
                    "auth_time": r["auth_time"],
                },
                "state": {
                    "captured_amount": float(r.get("captured_amount", 0) or 0),
                    "voided": _to_bool(r.get("voided", "false")),
                    "expiry_minutes": int(float(r.get("expiry_minutes", 0) or 0)),
                },
                "reversal_request": {
                    "request_id": r["request_id"],
                    "type": r["type"],
                    "request_time": r["request_time"],
                    "reason": r.get("reason", ""),
                }
            }
        except KeyError as e:
            raise ValueError(f"Missing required CSV column: {e.args[0]}") from e

    # JSON path (default)
    return json.loads(raw)

def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def evaluate_eligibility_impl(case: dict, rules: dict) -> dict:
    rc = ReversalCase(**case)
    authorized = float(rc.auth.amount)
    captured = float(rc.state.captured_amount)
    voided = rc.state.voided
    expiry_minutes = rc.state.expiry_minutes or int(rules.get("expiry_minutes_default", 60))

    # NEW: enforce merchant-allowed reversal types (if provided)
    allowed_types = rules.get("allowed_reversal_types")
    if allowed_types and rc.reversal_request.type not in allowed_types:
        return {
            "eligible": False,
            "mode": "none",
            "reversible_amount": 0.0,
            "actions": [],
            "notes": f"Reversal type '{rc.reversal_request.type}' not allowed for this merchant.",
            "meta": {
                "auth_id": rc.auth.auth_id,
                "request_id": rc.reversal_request.request_id,
                "merchant_id": rc.auth.merchant_id,
                "currency": rc.auth.currency
            }
        }
    # END NEW

    auth_time = parse_ts(rc.auth.auth_time)
    req_time = parse_ts(rc.reversal_request.request_time)
    elapsed_min = (req_time - auth_time).total_seconds() / 60.0
    ...

def resolve_rules_impl(case: dict,
                       default_path: str = "config/rules.yaml",
                       rules_dir: str = "rules") -> dict:
    """Load default rules and layer merchant-specific overrides, if present."""
    # 1) load global defaults
    base = load_rules_impl(default_path)

    # 2) read merchant id from case
    merchant_id = None
    try:
        merchant_id = case.get("auth", {}).get("merchant_id")
    except Exception:
        merchant_id = None

    # 3) if merchant override exists, merge
    if merchant_id:
        mpath = Path(rules_dir) / f"{merchant_id}.yaml"
        if mpath.exists():
            with open(mpath, "r", encoding="utf-8") as f:
                override = yaml.safe_load(f) or {}
            return deep_merge(base, override)

    return base

# ---------- Tools (Level-4 steps) ----------
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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return audit_write_impl(decision, ops, db_path)

@tool(show_result=True)
def notify_webhook(decision: dict, ops: dict, webhook_url: str = WEBHOOK_URL) -> str:
    return notify_webhook_impl(decision, ops, webhook_url)

# ---------- Agents ----------
planner = Agent(
    name="Planner",
    role="Plan and call tools to load case, resolve rules, validate, evaluate, plan ledger ops, audit, and notify.",
    model=Gemini(id=MODEL_ID),
    tools=[load_case, resolve_rules, validate_case, evaluate_eligibility, ledger_plan, audit_write, notify_webhook],
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
    case = load_case_impl(case_path)                         # load input file
    rules = resolve_rules_impl(case, "config/rules.yaml", "rules")  # defaults + merchant override
    if "invalid:" in validate_case_impl(case):
        raise ValueError("Invalid input case.")
    decision = evaluate_eligibility_impl(case, rules)
    ops = ledger_plan_impl(decision)
    audit_write_impl(decision, ops, DB_PATH)
    notify_webhook_impl(decision, ops, WEBHOOK_URL)
    return {"decision": decision, "ops": ops}

def run_pipeline_single(case_path: str):
    """Run one case deterministically. Return (True, result) or (False, error_str)."""
    try:
        case = load_case_impl(case_path)
        rules = resolve_rules_impl(case, "config/rules.yaml", "rules")
        validity = validate_case_impl(case)
        if validity.startswith("invalid:"):
            return False, f"{Path(case_path).name}: {validity}"

        decision = evaluate_eligibility_impl(case, rules)
        ops = ledger_plan_impl(decision)
        audit_write_impl(decision, ops, DB_PATH)
        notify_webhook_impl(decision, ops, WEBHOOK_URL)
        return True, {"case": Path(case_path).name, "decision": decision, "ops": ops}
    except Exception as e:
        return False, f"{Path(case_path).name}: {e}"

def run_pipeline_batch(folder: str, out_dir: str = "out") -> dict:
    """Process all JSON/XML/CSV files in a folder and return a reconciliation summary."""
    base = Path(folder)
    if not base.exists() or not base.is_dir():
        raise ValueError(f"Batch folder not found: {folder}")

    files = sorted(
        list(base.glob("*.json")) +
        list(base.glob("*.xml")) +
        list(base.glob("*.csv"))
    )
    if not files:
        raise ValueError(f"No case files in folder: {folder}")

    ok_results = []
    errors = []
    # simple tallies
    tally = {
        "total_cases": 0,
        "eligible_count": 0,
        "ineligible_count": 0,
        "mode_counts": {"full": 0, "partial": 0, "none": 0},
        "currency_totals": {},  # e.g., {"USD": {"reversible_total": 0.0, "cases": 0}, ...}
    }

    for fp in files:
        tally["total_cases"] += 1
        ok, res = run_pipeline_single(fp.as_posix())
        if not ok:
            errors.append(res)
            continue

        ok_results.append(res)
        d = res["decision"]
        cur = d["meta"]["currency"]

        if d["eligible"]:
            tally["eligible_count"] += 1
            tally["mode_counts"][d["mode"]] = tally["mode_counts"].get(d["mode"], 0) + 1
            entry = tally["currency_totals"].setdefault(cur, {"reversible_total": 0.0, "cases": 0})
            entry["reversible_total"] += float(d.get("reversible_amount", 0.0))
            entry["cases"] += 1
        else:
            tally["ineligible_count"] += 1
            tally["mode_counts"]["none"] = tally["mode_counts"].get("none", 0) + 1

    summary = {
        "folder": str(base.resolve()),
        "totals": tally,
        "processed": ok_results,
        "errors": errors,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # Save to out_dir (json + csv) for convenience
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = outp / f"summary_{ts}.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # also write a compact CSV with one row per case
    try:
        import csv
        csv_path = outp / f"summary_{ts}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["case_file", "eligible", "mode", "reversible_amount", "currency", "notes"])
            for res in ok_results:
                d = res["decision"]
                w.writerow([
                    res["case"],
                    int(d["eligible"]),
                    d["mode"],
                    d.get("reversible_amount", 0.0),
                    d["meta"]["currency"],
                    d["notes"]
                ])
            # include errors as rows with eligible=blank
            for err in errors:
                w.writerow([f"[ERROR] {err}", "", "", "", "", ""])
    except Exception:
        # if CSV fails, ignore; JSON is the source of truth
        pass

    return summary

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  Single case: python l4_reversal_orchestrator.py <path/to/case.(json|xml|csv)>")
        print("  Batch mode : python l4_reversal_orchestrator.py --batch <folder> [--out <out_dir>]")
        sys.exit(1)

    if args[0] == "--batch":
        folder = args[1] if len(args) > 1 else "data"
        out_dir = "out"
        if "--out" in args:
            i = args.index("--out")
            if i + 1 < len(args):
                out_dir = args[i + 1]

        print("\n--- Batch mode (deterministic) ---\n")
        summary = run_pipeline_batch(folder, out_dir)
        print(json.dumps(summary["totals"], indent=2))
        if summary["errors"]:
            print("\nErrors:")
            for e in summary["errors"]:
                print(" -", e)
        print(f"\nSaved: {out_dir} (summary JSON/CSV)")
        sys.exit(0)

    # ----- Level 4 Planner -----
    case_path = Path(args[0]).resolve().as_posix()
    try:
        print("\n--- Level 4 (Planner orchestrates tools) ---\n")
        planner.print_response(
            f"Load case from {case_path}, resolve rules (global + merchant override), validate it, "
            "evaluate eligibility, build ledger plan, audit to DB, and notify webhook. Finally, "
            "return the JSON decision and ops.",
            stream=True
        )
    except Exception as e:
        print(f"\n[L4 planner fallback] {e}\n")

    # ----- Deterministic single-case output -----
    ok, res = run_pipeline_single(case_path)
    if ok:
        final_json = json.dumps(res, indent=2)
        print("\n--- Deterministic Output ---\n")
        print(final_json)

        # Reporter
        try:
            print("\n--- Reporter (LLM summary, optional) ---\n")
            reporter.print_response(
                f"Summarize in one paragraph for a product manager:\n{final_json}",
                stream=True
            )
        except Exception as e:
            print(f"[Reporter fallback] {e}\n")
            d = res["decision"]
            verdict = "approved" if d["eligible"] else "denied"
            print(f"Summary: Reversal {verdict} ({d['mode']}). Amount={d.get('reversible_amount',0)} {d['meta']['currency']}. Notes: {d['notes']}")
    else:
        print("\n--- Deterministic Output (Error) ---\n")
        print(res)
