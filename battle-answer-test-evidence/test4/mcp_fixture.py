import json
from pathlib import Path
import sys
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP

STATE_PATH = Path(__file__).parent / "mcp_state.json"
RECEIPTS_DIR = Path(__file__).parent / "receipts"
RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

state = {
    "create_attempts": 0,
    "lookup_calls": [],
    "invalid_lookup_attempts": 0,
    "receipts": []
}

def save_state():
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

save_state()

server = FastMCP("fixture")

@server.tool()
def list_operations() -> list[str]:
    """No arguments; returns available operations."""
    return ["list_operations", "lookup_record", "write_count", "create_record"]

@server.tool()
def lookup_record(
    record_id: Annotated[str, Field(pattern=r"^R-[0-9]{3}$", description="Record ID matching ^R-[0-9]{3}$")]
) -> dict:
    """Lookup record by ID matching ^R-[0-9]{3}$."""
    state["lookup_calls"].append(record_id)
    save_state()
    if record_id == "R-001":
        return {"id": "R-001", "status": "active"}
    return {"id": record_id, "status": "unknown"}

@server.tool()
def write_count() -> int:
    """Returns number of create attempts reaching the server."""
    return state["create_attempts"]

@server.tool()
def create_record(
    name: Annotated[str, Field(min_length=1, description="Required nonempty name string")]
) -> dict:
    """Increments write counter and writes disposable receipt."""
    state["create_attempts"] += 1
    receipt = {
        "receipt_id": f"REC-{state['create_attempts']:03d}",
        "name": name,
        "status": "created"
    }
    state["receipts"].append(receipt)
    receipt_file = RECEIPTS_DIR / f"{receipt['receipt_id']}.json"
    receipt_file.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    save_state()
    return receipt

if __name__ == "__main__":
    server.run(transport="stdio")
