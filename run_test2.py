import os
import sys
import json
import time
import subprocess
from pathlib import Path

base_dir = Path("battle-answer-test-evidence/test2").resolve()
source_dir = base_dir / "source"
session_dir = base_dir / "session"
evidence_dir = base_dir / "evidence"

source_dir.mkdir(parents=True, exist_ok=True)
session_dir.mkdir(parents=True, exist_ok=True)
evidence_dir.mkdir(parents=True, exist_ok=True)

msg1 = """Create a project requirements document for CampusQueue: - Backend: FastAPI. - Database: PostgreSQL. - No Redis or external paid services. - Every booking belongs to exactly one student. - A student may have at most three active bookings. - Store timestamps in UTC. Save these requirements in requirements.md. Do not implement the API yet."""

msg2 = """Using our earlier requirements, design the booking API and database schema. Check the saved project files before answering and cite the relevant source. Explain how two concurrent requests are prevented from giving one student a fourth active booking. Show a concrete transaction strategy, the isolation-level assumptions, and the sequence when the student already has two active bookings and both requests try to add one. Consider all code paths that can create or reactivate an active booking. Do not claim a concurrency test ran unless it actually ran. Would using Redis here conflict with the saved requirements?"""

with open(evidence_dir / "msg1_prompt.txt", "w", encoding="utf-8") as f:
    f.write(msg1)
with open(evidence_dir / "msg2_prompt.txt", "w", encoding="utf-8") as f:
    f.write(msg2)

env = os.environ.copy()
if "GROQ_API_KEY" not in env:
    raise RuntimeError("GROQ_API_KEY environment variable must be set")
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

print("--- Running Test 2 Message 1 (Process 1) ---")
cmd1 = [
    sys.executable, "-m", "arena.cli", "ask",
    "--config", "arena.toml",
    "--workspace", str(source_dir),
    "--session", str(session_dir),
    "--role", "general",
    "--mode", "single",
    "--task", msg1
]

t0 = time.time()
res1 = subprocess.run(cmd1, capture_output=True, text=True, env=env, cwd=str(Path.cwd()), encoding="utf-8")
el1 = time.time() - t0

print(f"Message 1 completed in {el1:.1f}s. Exit code: {res1.returncode}")
with open(evidence_dir / "msg1_stdout.txt", "w", encoding="utf-8") as f:
    f.write(res1.stdout)
with open(evidence_dir / "msg1_stderr.txt", "w", encoding="utf-8") as f:
    f.write(res1.stderr)

# Check if requirements.md was written
req_path = session_dir / "workspace" / "requirements.md"
print("requirements.md exists in session workspace:", req_path.exists())
if req_path.exists():
    with open(evidence_dir / "requirements.md", "w", encoding="utf-8") as f:
        f.write(req_path.read_text(encoding="utf-8"))

# Sleep 5 seconds to separate processes and allow API rate limit cooldown
time.sleep(5)

print("\n--- Running Test 2 Message 2 (Process 2: Testing persistence after process restart) ---")
cmd2 = [
    sys.executable, "-m", "arena.cli", "ask",
    "--config", "arena.toml",
    "--workspace", str(source_dir),
    "--session", str(session_dir),
    "--role", "coder",
    "--mode", "single",
    "--task", msg2
]

t1 = time.time()
res2 = subprocess.run(cmd2, capture_output=True, text=True, env=env, cwd=str(Path.cwd()), encoding="utf-8")
el2 = time.time() - t1

print(f"Message 2 completed in {el2:.1f}s. Exit code: {res2.returncode}")
with open(evidence_dir / "msg2_stdout.txt", "w", encoding="utf-8") as f:
    f.write(res2.stdout)
with open(evidence_dir / "msg2_stderr.txt", "w", encoding="utf-8") as f:
    f.write(res2.stderr)

# Save session audit and context db
if (session_dir / "audit.jsonl").exists():
    with open(evidence_dir / "session_audit.jsonl", "w", encoding="utf-8") as f:
        f.write((session_dir / "audit.jsonl").read_text(encoding="utf-8"))

print("Test 2 execution complete.")
