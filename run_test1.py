import os
import sys
import json
import time
import subprocess
from pathlib import Path

# Setup directories
base_dir = Path("battle-answer-test-evidence/test1").resolve()
source_dir = base_dir / "source"
session_dir = base_dir / "session"
evidence_dir = base_dir / "evidence"

source_dir.mkdir(parents=True, exist_ok=True)
session_dir.mkdir(parents=True, exist_ok=True)
evidence_dir.mkdir(parents=True, exist_ok=True)

# Record before-manifest of source
before_manifest = [p.name for p in source_dir.iterdir()]
with open(evidence_dir / "source_manifest_before.json", "w") as f:
    json.dump(before_manifest, f, indent=2)

prompt = """Create booking.py with a function find_conflicts(bookings). Each booking is a dictionary containing id, start, and end. IDs are nonempty strings; timestamps use ISO 8601 with explicit timezone offsets. Return every conflicting pair of IDs, each pair sorted alphabetically, and the full result sorted lexicographically. Do not return duplicate pairs. Requirements: - Compare actual instants across timezone offsets. - Adjacent bookings do not overlap: intervals are [start, end). - Reject missing timezones, duplicate IDs, malformed timestamps, empty IDs, and end <= start with ValueError. - Handle empty input and intervals spanning midnight. - Do not modify the input list or its dictionaries. - Add at least ten meaningful regression tests. - Run the tests if execution is available. Otherwise state explicitly that they were not executed. Do not invent a passing result. Include this example: A: 2026-10-20T10:00:00+05:30 to 2026-10-20T11:00:00+05:30 B: 2026-10-20T05:00:00Z to 2026-10-20T06:00:00Z C: 2026-10-20T06:00:00Z to 2026-10-20T07:00:00Z Explain the algorithm, time complexity, files changed, actual checks, and any remaining limitations."""

with open(evidence_dir / "prompt.txt", "w", encoding="utf-8") as f:
    f.write(prompt)

cmd = [
    sys.executable, "-m", "arena.cli", "ask",
    "--config", "arena.toml",
    "--workspace", str(source_dir),
    "--session", str(session_dir),
    "--role", "coder",
    "--mode", "single",
    "--task", prompt
]

t0 = time.time()
env = os.environ.copy()
if "GROQ_API_KEY" not in env:
    raise RuntimeError("GROQ_API_KEY environment variable must be set")
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

res = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(Path.cwd()), encoding="utf-8")
elapsed = time.time() - t0

print(f"Done in {elapsed:.1f}s. Exit code: {res.returncode}")
with open(evidence_dir / "cli_stdout.txt", "w", encoding="utf-8") as f:
    f.write(res.stdout)
with open(evidence_dir / "cli_stderr.txt", "w", encoding="utf-8") as f:
    f.write(res.stderr)

# Check after-manifest of source directory (must remain unchanged!)
after_manifest = [p.name for p in source_dir.iterdir()]
with open(evidence_dir / "source_manifest_after.json", "w") as f:
    json.dump(after_manifest, f, indent=2)

source_unchanged = (before_manifest == after_manifest)
print("Source directory unchanged:", source_unchanged)

# Check session workspace
session_work = session_dir / "workspace"
workspace_files = [p.name for p in session_work.iterdir()] if session_work.exists() else []
print("Session workspace files:", workspace_files)
with open(evidence_dir / "session_workspace_manifest.json", "w") as f:
    json.dump(workspace_files, f, indent=2)

# Copy session artifacts/files to evidence
if session_work.exists():
    for f in session_work.glob("*"):
        if f.is_file():
            (evidence_dir / f.name).write_text(f.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

# Parse JSON answer from CLI if available
answer_obj = {}
try:
    answer_obj = json.loads(res.stdout)
    with open(evidence_dir / "answer.json", "w", encoding="utf-8") as f:
        json.dump(answer_obj, f, indent=2)
except Exception:
    pass

print("Test 1 run finished.")
