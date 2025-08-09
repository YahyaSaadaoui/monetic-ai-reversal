import json
from datetime import datetime, timezone
from pathlib import Path
import os
from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.google import Gemini 
from agno.tools import tool

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"
# Load variables from .env into environment
load_dotenv()

def _parse_ts(ts: str) -> datetime:
    # All timestamps are Zulu/UTC (e.g., 2025-08-09T14:05:00Z)
    return datetime.strptime(ts, ISO_FMT).replace(tzinfo=timezone.utc)

@tool(show_result=True, stop_after_tool_call=True)
def evaluate_reversal_from_file(path: str) -> str:
    """
    Read a JSON reversal case from `path`, evaluate eligibility, and return:
    - JSON block with decision & actions
    - Markdown one-liner summary
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    auth = data["auth"]
    state = data["state"]
    req = data["reversal_request"]

    authorized = float(auth["amount"])
    captured = float(state.get("captured_amount", 0.0))
    voided = bool(state.get("voided", False))
    expiry_minutes = int(state.get("expiry_minutes", 0))

    auth_time = _parse_ts(auth["auth_time"])
    req_time = _parse_ts(req["request_time"])
    elapsed_min = (req_time - auth_time).total_seconds() / 60.0

    # Default decision
    decision = {
        "eligible": False,
        "mode": "none",
        "reversible_amount": 0.0,
        "actions": [],
        "notes": ""
    }

    # Rule 1: already voided
    if voided:
        decision["notes"] = "Authorization already voided."
        result_json = json.dumps(decision, indent=2)
        md = "❌ Reversal denied (already voided)."
        return f"{result_json}\n\n{md}"

    # Rule 2: expired window
    if expiry_minutes and elapsed_min > expiry_minutes:
        decision["notes"] = f"Expired window: {elapsed_min:.1f} min > {expiry_minutes} min."
        result_json = json.dumps(decision, indent=2)
        md = "❌ Reversal denied (expired window)."
        return f"{result_json}\n\n{md}"

    # Compute reversible amount
    available = max(0.0, authorized - captured)
    if available <= 0:
        decision["notes"] = f"No funds on hold. Captured={captured:.2f} >= Authorized={authorized:.2f}."
        result_json = json.dumps(decision, indent=2)
        md = "❌ Reversal denied (nothing to release)."
        return f"{result_json}\n\n{md}"

    # If any capture > 0 => only partial reversal is possible
    if captured > 0:
        decision["eligible"] = True
        decision["mode"] = "partial"
        decision["reversible_amount"] = round(available, 2)
        decision["actions"] = [
            f"Release hold: {available:.2f} {auth['currency']} to card",
            f"Record reversal {req['request_id']} linked to {auth['auth_id']}",
            f"Notify merchant {auth['merchant_id']}"
        ]
        decision["notes"] = f"Captured {captured:.2f}, so only {available:.2f} remains reversible."
        result_json = json.dumps(decision, indent=2)
        md = f"✅ Reversal approved (partial). Release {available:.2f} {auth['currency']}. Capture already at {captured:.2f}."
        return f"{result_json}\n\n{md}"

    # Otherwise full amount is reversible (no capture yet)
    decision["eligible"] = True
    decision["mode"] = "full"
    decision["reversible_amount"] = round(available, 2)
    decision["actions"] = [
        f"Release hold: {available:.2f} {auth['currency']} to card",
        f"Record reversal {req['request_id']} linked to {auth['auth_id']}",
        f"Notify merchant {auth['merchant_id']}"
    ]
    decision["notes"] = "No capture yet; full amount is on hold."
    result_json = json.dumps(decision, indent=2)
    md = f"✅ Reversal approved (full). Release {available:.2f} {auth['currency']}."
    return f"{result_json}\n\n{md}"

# --- Agent definition (Level 3: reasoning + tool use)
agent = Agent(
    name="Reversal Eligibility & Impact Evaluator",
    role="Decide reversal eligibility, compute reversible amount, and list ledger actions.",
    model=Gemini(id="gemini-1.5-pro"),  # good free-tier default
    tools=[evaluate_reversal_from_file],
    reasoning=True,
    markdown=True,
)

if __name__ == "__main__":
    base = Path(__file__).resolve().parent
    case_path = base / "data" / "reversal_case.json"

    agent.print_response(
        f"Evaluate reversal using {case_path.as_posix()} and print JSON + a one-line markdown verdict.",
        stream=True,
        show_full_reasoning=False
    )
