# ui_tools.py
import os, json, tempfile
from pathlib import Path
from l4_reversal_orchestrator import run_pipeline_batch
from agno.tools import tool

# re-use your existing pure funcs & constants
from l4_reversal_orchestrator import (
    load_case_impl,
    resolve_rules_impl,
    validate_case_impl,
    evaluate_eligibility_impl,
    ledger_plan_impl,
    audit_write_impl,
    notify_webhook_impl,
    DB_PATH,
    WEBHOOK_URL,
)

def _run_process_case_from_path(path: str) -> dict:
    case = load_case_impl(path)
    rules = resolve_rules_impl(case, "config/rules.yaml", "rules")
    validity = validate_case_impl(case)
    if validity.startswith("invalid:"):
        raise ValueError(validity)

    decision = evaluate_eligibility_impl(case, rules)
    ops = ledger_plan_impl(decision)

    # side effects same as CLI
    audit_write_impl(decision, ops, DB_PATH)
    notify_webhook_impl(decision, ops, WEBHOOK_URL)
    return {"decision": decision, "ops": ops}

@tool(show_result=True, stop_after_tool_call=True)
def process_case(path: str) -> dict:
    """Deterministic pipeline for a single file already on disk."""
    return _run_process_case_from_path(path)

@tool(show_result=True, stop_after_tool_call=True)
def process_uploaded_file(filename: str, content_b64: str) -> dict:
    """
    Accepts a base64 file from the UI (json/xml/csv), writes to a temp file with the correct suffix,
    then runs the same pipeline as process_case.
    """
    import base64
    suffix = Path(filename).suffix.lower() or ".json"
    tmp_path = None
    try:
        data = base64.b64decode(content_b64)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        return _run_process_case_from_path(tmp_path)
    finally:
        if tmp_path and Path(tmp_path).exists():
            try: os.remove(tmp_path)
            except Exception: pass
