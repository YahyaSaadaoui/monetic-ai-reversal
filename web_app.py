import os, json, tempfile
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Reuse your existing logic (pure funcs + reporter)
from l4_reversal_orchestrator import (
    load_case_impl,
    resolve_rules_impl,
    validate_case_impl,
    evaluate_eligibility_impl,
    ledger_plan_impl,
    audit_write_impl,
    notify_webhook_impl,
    reporter,            # Agent for short human summary
    DB_PATH,
    WEBHOOK_URL,
)

app = FastAPI(title="Monetic Reversal UI")
templates = Jinja2Templates(directory="templates")

# (optional) serve /static if you later add CSS/JS
if Path("static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")


def _run_process_case_from_path(path: str) -> dict:
    """Exactly what your CLI does, but callable from HTTP."""
    case = load_case_impl(path)
    rules = resolve_rules_impl(case, "config/rules.yaml", "rules")
    validity = validate_case_impl(case)
    if validity.startswith("invalid:"):
        raise ValueError(validity)
    decision = evaluate_eligibility_impl(case, rules)
    ops = ledger_plan_impl(decision)
    # keep side effects, same as CLI
    audit_write_impl(decision, ops, DB_PATH)
    notify_webhook_impl(decision, ops, WEBHOOK_URL)
    return {"decision": decision, "ops": ops}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/process", response_class=JSONResponse)
async def api_process(
    file: UploadFile | None = File(default=None),
    # optional raw paste (json/xml) if user prefers text input
    pasted: str | None = Form(default=None),
):
    """
    Accept one file (JSON/XML/CSV) or text pasted in a textarea.
    We save it temporarily (to preserve your file-path loader) then run the pipeline.
    """
    tmp_path = None
    try:
        if file is None and (pasted is None or pasted.strip() == ""):
            return JSONResponse({"error": "No input provided"}, status_code=400)

        if file is not None:
            # honor original filename ext so your loader picks JSON/XML/CSV correctly
            suffix = Path(file.filename).suffix.lower() or ".json"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name
                tmp.write(await file.read())
        else:
            # user pasted content; try to guess format (very simple)
            body = pasted.strip()
            # detect XML vs JSON; default JSON
            suffix = ".xml" if body.startswith("<") else ".json"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name
                tmp.write(body.encode("utf-8"))

        result = _run_process_case_from_path(tmp_path)

        # Short human summary via your Reporter agent (Gemini)
        summary = ""
        try:
            final_json = json.dumps(result, indent=2)
            # reporter returns a streamed text in CLI; here we just get a single-shot response
            summary_resp = reporter.run(f"Summarize for a product manager:\n{final_json}")
            summary = summary_resp.content if hasattr(summary_resp, "content") else str(summary_resp)
        except Exception:
            # fall back to a manual one-liner if LLM unavailable
            d = result["decision"]
            verdict = "approved" if d["eligible"] else "denied"
            summary = f"Reversal {verdict} ({d['mode']}). Amount={d.get('reversible_amount',0)} {d['meta']['currency']}. Notes: {d['notes']}"

        return JSONResponse({
            "ok": True,
            "result": result,
            "summary": summary
        })
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    finally:
        if tmp_path and Path(tmp_path).exists():
            try:
                os.remove(tmp_path)
            except Exception:
                pass
