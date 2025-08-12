import os
from agno.agent import Agent
from agno.models.google import Gemini
from agno.playground import Playground
from agno.storage.sqlite import SqliteStorage

from ui_tools import process_case, process_uploaded_file
import base64
from fastapi import UploadFile, File, HTTPException

AGENT_DB = "tmp/agents.db"
os.makedirs("tmp", exist_ok=True)

# Your main UI agent
reversal_agent = Agent(
    name="Reversal Agent",
    model=Gemini(id=os.getenv("MODEL_ID", "gemini-1.5-flash")),
    tools=[process_case, process_uploaded_file],
    instructions=[
        "You evaluate reversal eligibility from uploaded JSON/XML/CSV files.",
        "If a user uploads a file, call `process_uploaded_file(filename, content_b64)`.",
        "If a user provides a local server path, call `process_case(path)`.",
        "Return only the result JSON unless the user asks for an explanation."
    ],
    storage=SqliteStorage(table_name="reversal_agent", db_file=AGENT_DB),
    add_datetime_to_instructions=True,
    add_history_to_messages=True,
    num_history_responses=5,
    markdown=True,
)

playground = Playground(agents=[reversal_agent])
app = playground.get_app()
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    try:
        content = await file.read()
        b64 = base64.b64encode(content).decode("utf-8")
        # Call your tool entrypoint directly (no LLM in the loop)
        result = process_uploaded_file.entrypoint(
            filename=file.filename,
            content_b64=b64
        )
        return result  # -> {"decision": {...}, "ops": {...}}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
if __name__ == "__main__":
    # runs uvicorn under the hood with reload
    playground.serve("playground:app", host="127.0.0.1", port=7777, reload=True)
