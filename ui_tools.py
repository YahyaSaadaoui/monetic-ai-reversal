# ui_tools.py
import os, json, tempfile
from pathlib import Path
from l4_reversal_orchestrator import run_pipeline_batch
from agno.tools import tool
import rarfile
import base64, tempfile, zipfile, os, json
from pathlib import Path
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
    import base64, tempfile, zipfile, os, json
    from pathlib import Path

    # ⬇️ NEW: import rarfile
    import rarfile

    suffix = Path(filename).suffix.lower() or ".json"
    tmp_path = None
    try:
        data = base64.b64decode(content_b64)

        # ZIP/RAR => unpack and run batch on the extracted folder
        if suffix in (".zip", ".rar"):
            with tempfile.TemporaryDirectory() as tmpdir:
                if suffix == ".zip":
                    zippath = Path(tmpdir) / "upload.zip"
                    zippath.write_bytes(data)
                    with zipfile.ZipFile(zippath, "r") as zf:
                        zf.extractall(tmpdir)
                else:
                    rarpath = Path(tmpdir) / "upload.rar"
                    rarpath.write_bytes(data)
                    try:
                        with rarfile.RarFile(rarpath) as rf:
                            rf.extractall(tmpdir)
                    except rarfile.RarCannotExec:
                        raise RuntimeError(
                            "RAR support requires the 'unrar' binary installed and available on PATH."
                        )
                    except rarfile.BadRarFile as e:
                        raise RuntimeError(f"Invalid RAR file: {e}")

                # run your existing batch pipeline on the extracted folder
                from l4_reversal_orchestrator import run_pipeline_batch
                summary = run_pipeline_batch(tmpdir, out_dir="out")
                return {"batch_summary": summary}

        # Single-file path (json/xml/csv) -> deterministic pipeline
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        return _run_process_case_from_path(tmp_path)

    finally:
        if tmp_path and Path(tmp_path).exists():
            try:
                os.remove(tmp_path)
            except Exception:
                pass