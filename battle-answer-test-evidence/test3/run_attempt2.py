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
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR = ATTEMPT2_DIR / "session"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
FIXTURE_URL = "http://127.0.0.1:8910"

PROMPT_PRIMARY = (
    f"Inspect the booking form at {FIXTURE_URL} with the enabled browser tools. "
    "Report its actual visible fields and initial status before making changes. "
    "Request approval to fill a booking using Name TEST-Arena and Slot 10:00. "
    "Before clicking Save booking, request approval for that specific action. "
    "Do not submit until that action is approved. "
    "After submission, inspect the actual visible result and network evidence. "
    "Save a browser screenshot. Explain what evidence supports success. "
    "If the page is unavailable, report the connection failure instead of inventing fields, a screenshot, or a successful booking."
)

PROMPT_UNAVAILABLE = (
    f"Inspect the booking form at {FIXTURE_URL} with the enabled browser tools. "
    "Report its actual visible fields and initial status before making changes. "
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

def run_attempt2():
    print("=== TEST 3 ATTEMPT 2: RUNNING BROWSER & CHAT UI EVALUATION ===")
    config = load(str(REPO_ROOT / "arena.toml"))
    
    # 1. Initial State Check
    init_state = query_fixture_state()
    print("Initial fixture state:", init_state)
    (EVIDENCE_DIR / "initial_state.json").write_text(json.dumps(init_state, indent=2))
    assert init_state["count"] == 0, "Fixture state must initially have 0 bookings!"

    # 2. Start Chat UI Server
    server = make_server(config, SESSION_DIR, {"allow_browser": True}, port=0)
    server_port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"Chat UI server started on http://127.0.0.1:{server_port}")

    approval_log = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=CHROME_PATH)
            page = browser.new_page(viewport={"width": 800, "height": 900})
            
            chat_url = f"http://127.0.0.1:{server_port}"
            page.goto(chat_url)
            page.wait_for_load_state("networkidle")
            
            (EVIDENCE_DIR / "prompt_primary.txt").write_text(PROMPT_PRIMARY, encoding="utf-8")
            
            # Submit primary task in Chat UI
            page.get_by_label("Your task", exact=True).fill(PROMPT_PRIMARY)
            page.get_by_role("button", name="Run task").click()
            print("Primary prompt submitted via Chat UI. Awaiting steps and approvals...")

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
                    print(f"\n[APPROVAL REQUESTED] Tool: {tool}, Args: {args}")
                    
                    # Independent verification before approving Save button click
                    if tool == "browser_click":
                        st = query_fixture_state()
                        print("[INDEPENDENT CHECK BEFORE CLICK APPROVAL] Current state:", st)
                        (EVIDENCE_DIR / f"state_before_approval_{last_pending_id}.json").write_text(json.dumps(st, indent=2))
                    
                    approval_log.append({
                        "id": last_pending_id,
                        "time": time.time(),
                        "tool": tool,
                        "arguments": args,
                        "action": "approved"
                    })
                    
                    # Wait briefly for UI to display approval
                    time.sleep(0.5)
                    allow_btn = page.locator("#allow")
                    if allow_btn.is_visible():
                        allow_btn.click()
                        print("[APPROVAL ACTION] Clicked #allow in Chat UI.")
                    else:
                        print("[APPROVAL ACTION] #allow not visible; approving via state directly as fallback.")
                        server.chat_state.approved = True
                        server.chat_state.decision.set()

                if not state.get("running"):
                    if state.get("answer") or state.get("error"):
                        print("\nPrimary task completed!")
                        break

            # Check final fixture state after primary run
            final_state = query_fixture_state()
            print("\n[INDEPENDENT CHECK AFTER COMPLETION] Final fixture state:", final_state)
            (EVIDENCE_DIR / "final_state.json").write_text(json.dumps(final_state, indent=2))
            
            fixture_logs = query_fixture_logs()
            (EVIDENCE_DIR / "fixture_logs.json").write_text(json.dumps(fixture_logs, indent=2))
            (EVIDENCE_DIR / "approval_log.json").write_text(json.dumps(approval_log, indent=2))
            
            chat_state = server.chat_state.view()
            (EVIDENCE_DIR / "chat_state.json").write_text(json.dumps(chat_state, indent=2, default=str), encoding="utf-8")
            
            if chat_state.get("answer"):
                (EVIDENCE_DIR / "answer_primary.txt").write_text(json.dumps(chat_state["answer"], indent=2), encoding="utf-8")
                print("Model Primary Answer received.")
            if chat_state.get("error"):
                (EVIDENCE_DIR / "error_primary.txt").write_text(str(chat_state["error"]), encoding="utf-8")
                print("Primary Error received:", chat_state["error"])

            # Save screenshots from artifacts
            artifacts_dir = SESSION_DIR / "artifacts"
            if artifacts_dir.exists():
                for sc in artifacts_dir.glob("browser-*.png"):
                    dest = EVIDENCE_DIR / sc.name
                    dest.write_bytes(sc.read_bytes())
                    print("Found and preserved screenshot artifact:", sc.name)

            browser.close()

    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()

    print("\nPrimary run complete. Next: Unavailable-app subtest.")

if __name__ == "__main__":
    run_attempt2()
