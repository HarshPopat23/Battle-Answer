import json
import os
import sys
import time
import urllib.request
import threading
from pathlib import Path

REPO_ROOT = Path(r"d:\20+pro\Battle-Answer\Battle-Answer")
sys.path.insert(0, str(REPO_ROOT))

from arena.config import load
from arena.server import make_server
from playwright.sync_api import sync_playwright

ATTEMPT2_DIR = REPO_ROOT / "battle-answer-test-evidence" / "test3" / "attempt2"
EVIDENCE_DIR = ATTEMPT2_DIR / "evidence"
SESSION_DIR = ATTEMPT2_DIR / "session"

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FIXTURE_URL = "http://127.0.0.1:8910"

PROMPT_APPROVAL = (
    "I explicitly approve filling the form with Name 'TEST-Arena' and Slot '10:00'. "
    "I also explicitly approve clicking 'Save booking'. "
    "Please proceed with filling the fields and clicking Save booking now. "
    "After submission, inspect the actual visible result and network evidence. "
    "Save a browser screenshot and explain what evidence supports success."
)

def query_fixture_state():
    req = urllib.request.Request(f"{FIXTURE_URL}/state")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())

def query_fixture_logs():
    req = urllib.request.Request(f"{FIXTURE_URL}/logs")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())

def run_turn2():
    print("=== TEST 3 ATTEMPT 2: RUNNING TURN 2 (APPROVED MUTATION & SUBMISSION) ===")
    config = load(str(REPO_ROOT / "arena.toml"))
    
    # State before Turn 2
    state_before = query_fixture_state()
    print("State before Turn 2:", state_before)
    (EVIDENCE_DIR / "turn2_state_before.json").write_text(json.dumps(state_before, indent=2))
    assert state_before["count"] == 0, "Fixture state must be 0 before Turn 2!"

    server = make_server(config, SESSION_DIR, {"allow_browser": True}, port=0)
    server_port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"Chat UI server started on http://127.0.0.1:{server_port}")

    turn2_approvals = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=CHROME_PATH)
            page = browser.new_page(viewport={"width": 800, "height": 900})
            
            chat_url = f"http://127.0.0.1:{server_port}"
            page.goto(chat_url)
            page.wait_for_load_state("networkidle")
            
            (EVIDENCE_DIR / "prompt_turn2.txt").write_text(PROMPT_APPROVAL, encoding="utf-8")
            
            # Submit Turn 2 in Chat UI
            page.get_by_label("Your task", exact=True).fill(PROMPT_APPROVAL)
            page.get_by_role("button", name="Run task").click()
            print("Turn 2 prompt submitted via Chat UI. Awaiting steps and approvals...")

            start_time = time.time()
            last_pending_id = None

            while time.time() - start_time < 300:
                time.sleep(1.0)
                state = server.chat_state.view()
                
                # Check for approval
                pending = state.get("approval")
                if pending and pending.get("id") != last_pending_id:
                    last_pending_id = pending["id"]
                    tool = pending.get("tool")
                    args = pending.get("arguments", {})
                    print(f"\n[TURN 2 APPROVAL REQUESTED] Tool: {tool}, Args: {args}")
                    
                    if tool == "browser_click":
                        st = query_fixture_state()
                        print("[INDEPENDENT CHECK BEFORE CLICK APPROVAL] Current state:", st)
                        (EVIDENCE_DIR / f"turn2_state_before_click_{last_pending_id}.json").write_text(json.dumps(st, indent=2))
                    
                    turn2_approvals.append({
                        "id": last_pending_id,
                        "time": time.time(),
                        "tool": tool,
                        "arguments": args,
                        "action": "approved"
                    })
                    
                    # Approve action
                    time.sleep(0.5)
                    allow_btn = page.locator("#allow")
                    if allow_btn.is_visible():
                        allow_btn.click()
                        print("[APPROVAL ACTION] Clicked #allow in Chat UI.")
                    else:
                        print("[APPROVAL ACTION] Approving via state directly.")
                        server.chat_state.approved = True
                        server.chat_state.decision.set()

                if not state.get("running"):
                    if state.get("answer") or state.get("error"):
                        print("\nTurn 2 completed!")
                        break

            # Check final fixture state after turn 2
            state_after = query_fixture_state()
            print("\n[INDEPENDENT CHECK AFTER TURN 2] Final fixture state:", state_after)
            (EVIDENCE_DIR / "turn2_state_after.json").write_text(json.dumps(state_after, indent=2))
            
            fixture_logs = query_fixture_logs()
            (EVIDENCE_DIR / "turn2_fixture_logs.json").write_text(json.dumps(fixture_logs, indent=2))
            (EVIDENCE_DIR / "turn2_approval_log.json").write_text(json.dumps(turn2_approvals, indent=2))
            
            chat_state = server.chat_state.view()
            (EVIDENCE_DIR / "turn2_chat_state.json").write_text(json.dumps(chat_state, indent=2, default=str), encoding="utf-8")
            
            if chat_state.get("answer"):
                (EVIDENCE_DIR / "answer_turn2.txt").write_text(json.dumps(chat_state["answer"], indent=2), encoding="utf-8")
                print("Model Turn 2 Answer received.")
            if chat_state.get("error"):
                (EVIDENCE_DIR / "error_turn2.txt").write_text(str(chat_state["error"]), encoding="utf-8")
                print("Turn 2 Error received:", chat_state["error"])

            # Save screenshots
            artifacts_dir = SESSION_DIR / "artifacts"
            if artifacts_dir.exists():
                for sc in artifacts_dir.glob("browser-*.png"):
                    dest = EVIDENCE_DIR / sc.name
                    dest.write_bytes(sc.read_bytes())
                    print("Found screenshot artifact:", sc.name)

            browser.close()

    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()

if __name__ == "__main__":
    run_turn2()
