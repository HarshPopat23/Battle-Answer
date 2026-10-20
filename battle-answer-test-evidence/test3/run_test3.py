import json
import os
import sys
import time
import urllib.request
import threading
from pathlib import Path

# Set up paths and config
REPO_ROOT = Path(r"d:\20+pro\Battle-Answer\Battle-Answer")
sys.path.insert(0, str(REPO_ROOT))

from arena.config import load
from arena.server import make_server
from playwright.sync_api import sync_playwright

EVIDENCE_DIR = REPO_ROOT / "battle-answer-test-evidence" / "test3" / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR = REPO_ROOT / "battle-answer-test-evidence" / "test3" / "session"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FIXTURE_URL = "http://127.0.0.1:8910"

PROMPT = (
    f"Inspect the booking form at {FIXTURE_URL} with the enabled browser tools. "
    "Report its actual visible fields and initial status before making changes. "
    "Request approval to fill a booking using Name TEST-Arena and Slot 10:00. "
    "Before clicking Save booking, request approval for that specific action. "
    "Do not submit until that action is approved. "
    "After submission, inspect the actual visible result and network evidence. "
    "Save a browser screenshot. Explain what evidence supports success. "
    "If the page is unavailable, report the connection failure instead of inventing fields, a screenshot, or a successful booking."
)

def query_fixture_state():
    req = urllib.request.Request(f"{FIXTURE_URL}/state")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())

def query_fixture_logs():
    req = urllib.request.Request(f"{FIXTURE_URL}/logs")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())

def run_test3():
    print("=== TEST 3: BROWSER INSPECTION, MUTATION, AND UNAVAILABLE-APP TEST ===")
    config = load(str(REPO_ROOT / "arena.toml"))
    
    # Verify initial fixture state
    init_state = query_fixture_state()
    print("Initial fixture state:", init_state)
    (EVIDENCE_DIR / "initial_state.json").write_text(json.dumps(init_state, indent=2))
    assert init_state["count"] == 0, "Fixture state must initially have 0 bookings!"

    # Start chat server
    server = make_server(config, SESSION_DIR, {"allow_browser": True}, port=0)
    server_port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"Chat UI server started on http://127.0.0.1:{server_port}")

    approval_log = []
    before_save_state = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=CHROME_PATH)
            page = browser.new_page(viewport={"width": 800, "height": 900})
            
            chat_url = f"http://127.0.0.1:{server_port}"
            print("Opening chat UI at", chat_url)
            page.goto(chat_url)
            page.wait_for_load_state("networkidle")
            
            # Save prompt
            (EVIDENCE_DIR / "prompt.txt").write_text(PROMPT, encoding="utf-8")
            
            # Submit task in chat UI
            page.get_by_label("Your task", exact=True).fill(PROMPT)
            page.get_by_role("button", name="Run task").click()
            print("Submitted task through Chat UI...")

            # Monitor loop for approvals and task completion
            start_time = time.time()
            completed = False
            last_pending_id = None

            while time.time() - start_time < 240:
                time.sleep(1.0)
                state = server.chat_state.view()
                
                # Check for pending approval
                pending = state.get("approval")
                if pending and pending.get("id") != last_pending_id:
                    last_pending_id = pending["id"]
                    tool = pending.get("tool")
                    args = pending.get("arguments", {})
                    print(f"Approval requested: {tool} with args: {args}")
                    
                    # Independent check before approving Save booking
                    if tool == "browser_click":
                        st = query_fixture_state()
                        before_save_state = st
                        print("State before approving click:", st)
                        (EVIDENCE_DIR / f"state_before_approval_{last_pending_id}.json").write_text(json.dumps(st, indent=2))
                    
                    approval_log.append({
                        "id": last_pending_id,
                        "time": time.time(),
                        "tool": tool,
                        "arguments": args,
                        "action": "approved"
                    })
                    
                    # Click Approve this action in the Chat UI
                    approve_btn = page.locator("#allow")
                    if approve_btn.is_visible():
                        approve_btn.click()
                        print("Clicked 'Approve this action' button in Chat UI.")
                    else:
                        print("Approve button not visible yet, waiting...")

                if not state.get("running"):
                    if state.get("answer") or state.get("error"):
                        completed = True
                        print("Task completed!")
                        break

            # Save state after completion
            final_state = query_fixture_state()
            print("Final fixture state:", final_state)
            (EVIDENCE_DIR / "final_state.json").write_text(json.dumps(final_state, indent=2))
            
            fixture_logs = query_fixture_logs()
            (EVIDENCE_DIR / "fixture_logs.json").write_text(json.dumps(fixture_logs, indent=2))
            
            (EVIDENCE_DIR / "approval_log.json").write_text(json.dumps(approval_log, indent=2))
            
            chat_state = server.chat_state.view()
            (EVIDENCE_DIR / "chat_state.json").write_text(json.dumps(chat_state, indent=2, default=str), encoding="utf-8")
            
            if chat_state.get("answer"):
                (EVIDENCE_DIR / "answer.txt").write_text(json.dumps(chat_state["answer"], indent=2), encoding="utf-8")
                print("Model Answer received.")
            if chat_state.get("error"):
                (EVIDENCE_DIR / "error.txt").write_text(str(chat_state["error"]), encoding="utf-8")
                print("Error received:", chat_state["error"])

            browser.close()

    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()

    print("Test 3 primary run finished.")

if __name__ == "__main__":
    run_test3()
