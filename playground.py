# playground.py
import os
from agno.agent import Agent
from agno.models.google import Gemini
from agno.playground import Playground
from agno.storage.sqlite import SqliteStorage
from agno.playground import Playground
from fastapi.middleware.cors import CORSMiddleware
from ui_tools import process_case, process_uploaded_file
import base64
from fastapi import UploadFile, File, HTTPException

# ⬇️ add this import to summarize
import json
from l4_reversal_orchestrator import reporter  # already defined in your code
from agno.tools import tool

AGENT_DB = "tmp/agents.db"
os.makedirs("tmp", exist_ok=True)
_last_result: dict | None = None
@tool(show_result=False)
def remember_last_result(result: dict) -> str:
    global _last_result
    _last_result = result
    return "stored"

@tool(show_result=True)
def recall_last_result() -> dict:
    return _last_result or {"info": "no result stored yet"}

reversal_agent = Agent(
    name="Reversal Agent",
    model=Gemini(id=os.getenv("MODEL_ID", "gemini-1.5-flash")),
    tools=[process_case, process_uploaded_file, remember_last_result, recall_last_result],
    instructions=[
        "You evaluate reversal eligibility from uploaded JSON/XML/CSV files.",
        "If a user uploads a file, call `process_uploaded_file(filename, content_b64)`.",
        "If a user provides a local server path, call `process_case(path)`.",
        "Return only the result JSON unless the user asks for an explanation.",
        "If the user asks about the last case, call `recall_last_result()` and summarize it",
        "After ,user submit the file what ever the type call the `recall_last_result()` if no resulst are showed to him"
    ],
    storage=SqliteStorage(table_name="reversal_agent", db_file=AGENT_DB),
    add_datetime_to_instructions=True,
    add_history_to_messages=True,
    num_history_responses=5,
    markdown=True,
)

playground = Playground(agents=[reversal_agent])
app = playground.get_app()

def summarize_result(raw: dict) -> str:
    """
    Always return a short, human-readable summary.
    No LLM. No code fences. No JSON.
    """
    try:
        # Batch mode
        if "batch_summary" in raw:
            s = raw["batch_summary"]
            t = s.get("totals", {})
            total = t.get("total_cases", 0)
            eligible = t.get("eligible_count", 0)
            ineligible = t.get("ineligible_count", 0)
            mc = t.get("mode_counts", {}) or {}
            full = mc.get("full", 0)
            partial = mc.get("partial", 0)

            bits = [
                f"Processed {total} cases.",
                f"Eligible: {eligible} (full {full}, partial {partial}).",
                f"Ineligible: {ineligible}."
            ]

            # optional currency totals
            ct = t.get("currency_totals", {}) or {}
            if ct:
                cur_parts = []
                for cur, v in ct.items():
                    cur_parts.append(
                        f"{cur}: reversible total {v.get('reversible_total', 0)} over {v.get('cases', 0)} cases"
                    )
                bits.append("By currency: " + "; ".join(cur_parts))

            return " ".join(bits)

        # Single case
        d = raw["decision"]
        verdict = "eligible" if d.get("eligible") else "not eligible"
        mode = d.get("mode", "none")
        amt = d.get("reversible_amount", 0)
        cur = d.get("meta", {}).get("currency", "")
        notes = d.get("notes", "")

        # Short, plain sentence:
        # ex: "Reversal eligible (full). Amount 75 USD. Notes: No capture yet; full amount is on hold."
        amt_txt = f"Amount {amt} {cur}." if amt else "Amount 0."
        mode_txt = f"({mode})" if mode and mode != "none" else "(none)"
        notes_txt = f" Notes: {notes}" if notes else ""

        return f"Reversal {verdict} {mode_txt}. {amt_txt}{notes_txt}"
    except Exception:
        # last-resort fallback
        return "Processed the file. (Could not build a summary.)"
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    try:
        content = await file.read()
        b64 = base64.b64encode(content).decode("utf-8")

        raw = process_uploaded_file.entrypoint(
            filename=file.filename,
            content_b64=b64
        )

        # 3) Use the deterministic summary
        summary_text = summarize_result(raw)

        # (optional) remember last result
        try:
            remember_last_result.entrypoint(result=raw)
        except Exception:
            pass

        return {"ok": True, "summary": summary_text}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|"
                       r"192\.168\.\d{1,3}\.\d{1,3}|"
                       r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
                       r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    playground.serve("playground:app", host="127.0.0.1", port=7777, reload=True)
