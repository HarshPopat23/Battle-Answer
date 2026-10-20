# Battle-Answer (Arena Standalone)

Use a persistent assistant for everyday work, or give a task to several LLM workers, let their solutions challenge and improve each other, and select a winner with a configurable judge. This fork replaces the Claude Code plugin with a standalone Python application.

Version 0.3 adds a local chat UI, project and conversation retrieval, PDF/DOCX text extraction, an opt-in Chromium browser, and persistent MCP connections for external tools such as API Anything and REA. See [assistant setup](docs/ASSISTANT.md) and [research and integration decisions](docs/INTEGRATIONS.md).

The original strategy dealer, rubric, and elimination bracket are preserved from [Jake Schincariol's Arena](https://github.com/Jakeschincariol/arena-skill). The MIT license and attribution remain intact.

## Quick start

Requires Python 3.11+. The base installation has no runtime dependencies; browser, MCP, and PDF support use optional extras. No Claude Code installation is needed.

```bash
git clone https://github.com/HarshPopat23/Battle-Answer.git
cd Battle-Answer
# For the v0.3 changes before the PR is merged:
git switch feat/assistant-tools
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp examples/groq.toml arena.toml
export GROQ_API_KEY='your-key-here'
arena plan --config arena.toml
arena doctor --config arena.toml
arena serve --config arena.toml --session .arena/my-assistant
# Open http://127.0.0.1:8765. Or use a tournament directly:
# arena run --config arena.toml --task "Design a simple study planner" --dir .arena/planner
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and set `$env:GROQ_API_KEY = 'your-key-here'` instead of `export`. Commands also work as `python -m arena ...` without installation.

Model IDs in examples are starting points, not availability promises. Choose IDs available to your account from the provider's current model list. API usage is billed by your provider; local models need suitable hardware. Keep keys in environment variables, not config files, task text, commits, or PRs.

## Providers and model roles

| `provider` | Contract / default credential variable |
| --- | --- |
| `groq` | OpenAI-compatible chat completions / `GROQ_API_KEY` |
| `openai` | Chat completions / `OPENAI_API_KEY` |
| `openrouter` | Chat completions / `OPENROUTER_API_KEY` |
| `ollama` | Local OpenAI-compatible API at `http://localhost:11434/v1`; no key by default |
| `openai-compatible` | Custom `api_base` required / `ARENA_API_KEY` by default |
| `anthropic` | Native Messages API / `ANTHROPIC_API_KEY` |
| `gemini` | Native GenerateContent API / `GEMINI_API_KEY` |

Each role has independent model, endpoint, key environment reference, timeout, output-token limit, and retries. `examples/mixed.toml` demonstrates a Gemini worker, Anthropic judge, and Groq fallback; `examples/ollama.toml` demonstrates local inference.

Support means these API contracts, not every possible model. Models must follow the JSON action/answer protocol and reason well enough for the task. Native API function calling is not required. Malformed responses receive bounded repair attempts, then an explicitly configured fallback if present. Arena stops if that fails rather than inventing output. `token_parameter` overrides `max_tokens` / `max_completion_tokens` for compatible endpoints. Temperature is omitted unless configured.

Use a stronger, independently evaluated `[judge]` when weaker workers are inadequate. `[fallback]` applies to either role after protocol failures; it is never selected silently and actual model usage is logged. `arena doctor` makes two small paid calls checking JSON/simple arithmetic. A new run also performs those checks. They are readiness signals, not coding or judging benchmarks.

Reference contracts: [Groq](https://console.groq.com/docs/api-reference), [Anthropic](https://platform.claude.com/docs/en/api/overview), [Gemini](https://ai.google.dev/api/generate-content), and your compatible endpoint's documentation.

## Tournament

1. Competitors receive the exact same task plus distinct reasoning/workflow/strategy cards.
2. They solve it with the available tools.
3. Paired competitors challenge each other's answers and defend/revise their own work.
4. The judge scores candidates labeled X/Y, without cards or agent IDs in the wrapper. Default: two votes with reversed candidate order; average scores, retain fatal findings, report disagreements.
5. Winners advance until one remains. An optional baseline receives a final blinded comparison.

Swapping order reduces one form of position bias; it does not make votes independent or guarantee correctness. Candidate content itself can reveal its source. A tournament does not make a weak model reliable automatically.

## Coding tasks and tools

```bash
arena run --config arena.toml \
  --task "Fix the parser bug and add a regression test" \
  --workspace /absolute/path/to/project \
  --dir .arena/parser-fix
```

Each competitor receives a separate filtered project copy. Original files are never automatically edited.

| Tool | Boundary |
| --- | --- |
| `list_files`, `read_file`, `search_text` | Assigned workspace, relative paths; no symlink traversal or excluded credential paths |
| `write_file` | Competitor's copy only; disabled for attackers/judges |
| `run_command` | Requires `--allow-exec`; Docker only, never a host shell |
| `fetch_url` | Requires exact `arena.web_hosts`; HTTPS text with public IP pinning, no redirects |
| `read_document`, `context_search`, `history_search` | Document text in the copy; source/line retrieval and conversation memory in assistant sessions |
| `browser_*` | Optional Playwright extra, configured exact origins and `--allow-browser`; click/fill/press require approval |
| `mcp_<server>__<tool>` | Optional MCP extra and `--allow-mcp`; explicit tool selection and schema validation; configured write tools require approval |
| Judge candidate-file tools | Read-only inspection of X/Y workspaces |

`fetch_url` remains a text-only fetch. The optional browser adds JavaScript rendering, DOM interactions, tabs, screenshots, and bounded console/network evidence in a fresh context. Browser redirects are blocked. MCP servers are trusted external programs/services and can operate outside the project copy; their permissions differ from the local file/Docker tools. Read [the full boundaries and setup](docs/ASSISTANT.md) before enabling them. Arena does not reproduce every Claude Code feature.

### Execute and verify code

Prepare a trusted Docker image containing your test dependencies before a run. Containers have no network and cannot install dependencies during the task.

```bash
docker pull python:3.12-slim
```

Configure the existing `[arena]` section:

```toml
[arena]
agents = 4
judge_votes = 2
docker_image = "python:3.12-slim"
verify_argv = ["python", "-m", "unittest", "discover", "-s", "tests"]
```

Add `--allow-exec` to `arena run`. The configured verification command runs after each initial/revised candidate, independently of model claims. A known failed candidate cannot eliminate a known passed candidate; conflicting fatal findings pause the run. Zero exit status establishes only that the configured check passed: choose meaningful tests and inspect changes to test files.

Docker uses only the assigned workspace mount, disabled networking, dropped capabilities, no-new-privileges, a read-only root filesystem, process/memory/CPU limits, bounded retained output, and timeouts. No API-key environment variables or Docker socket are mounted. The workspace remains writable without a disk quota; this is not a VM or a guarantee against container escapes. Use a separate VM for workloads requiring stronger isolation.

Snapshots omit `.git`, dependency environments, symlinks, `.env*`, common credential files/directories, and key files. Limits: 3000 files / 32 MiB per snapshot; 128 KiB per tool file read/write. Name filters cannot identify every secret: inspect your selected project first. Source/tool results may be sent to your configured providers, and run directories contain sensitive task/evidence data.

## Outputs

| File / directory | Contents |
| --- | --- |
| `winner.md` | Winning revised answer |
| `winner.patch` | Text diff against the filtered source snapshot; review before applying |
| `report.json` | Winner, checks, review notes, baseline comparison, usage |
| `workspaces/<agent>/` | Candidate files, including the winning workspace |
| `jobs/`, `r0/`, `r1/`, ... | Checkpoints, solutions, attacks, defenses, judge votes |
| `audit.jsonl`, `usage.json` | Model/tool evidence and request/token accounting |

No external verification means `needs_review`. Failed winner verification, vote disagreement, or retained fatal findings also require review. `passed_configured_checks` refers only to your command and flagged conditions, not correctness. Binary changes need manual copying from the winning workspace. Text patches do not preserve binary data or file-mode changes.

## Budgets and resume

Default: four competitors, two parallel worker jobs, two judge votes per match: 22 base generation requests plus two preflight requests. Tools, repairs, fallback, and HTTP retries add requests. Use `arena plan` before spending.

`max_calls` counts every HTTP attempt including retries and stops new requests at the limit. `max_total_tokens` tracks reported usage and reserves conservative in-flight allowances; missing usage and failed responses are charged estimates. Tokenization, provider billing, and ambiguous network failures prevent an exact monetary cap. Use provider-side spending controls for that.

Provider failures, malformed/truncated output, or exhausted budgets pause instead of fabricating winners. Finished jobs/votes are checkpointed. A job interrupted before its receipt is durable can be repeated and billed again; its partially edited copy remains for inspection.

```bash
arena status --dir .arena/parser-fix
arena resume --config arena.toml --dir .arena/parser-fix
```

Resume requires the original absolute run path, models/task/tools/verification settings. Budgets and concurrency may be changed explicitly. Source/task/rubric and completed-output hashes are checked. A lock rejects concurrent runners. If a killed process leaves `.run.lock`, confirm the process/container stopped before deleting it. CLI overrides such as `--agents` must be reflected in the resume config.

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q arena
python -m arena plan --config examples/groq.toml
```

Tests cover the original bracket, API wire fixtures, model doubles for tournaments and multi-turn assistance, file/patch isolation, document retrieval, local UI approvals, real stdio/HTTP MCP fixtures, and Chromium interactions. Optional tests skip when their dependencies/browser are missing; the integration CI job installs all extras and requires them. Docker execution remains mocked. These tests do not establish hosted-model answer quality, live Docker acceptance, or the correctness of third-party MCP applications. No real API keys are needed.

```bash
python -m pip install -e '.[all]'
python -m playwright install chromium
ARENA_REQUIRE_INTEGRATION=1 python -m unittest discover -s tests -v
```

The low-level bracket CLI remains at `python -m arena.bracket ...`. The standalone runner owns API calls, tools, stricter response validation, checkpoints, and evidence. Claude marketplace packaging and `SKILL.md` orchestration have been removed.
