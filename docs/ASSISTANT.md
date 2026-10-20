# Assistant, browser, and MCP setup

The Python package is `arena-standalone`; the executable remains `arena`. You can run it in a terminal inside Antigravity or any editor. No Claude plugin is installed or required.

## Start with one model key

```bash
python -m pip install -e '.[all]'
python -m playwright install chromium
cp examples/groq.toml arena.toml
export GROQ_API_KEY='your-key-here'
arena doctor --config arena.toml
arena serve --config arena.toml --workspace /absolute/path/to/project --session .arena/my-project
```

On Linux, Chromium may also need system libraries: `python -m playwright install --with-deps chromium`. On Windows PowerShell use `$env:GROQ_API_KEY = 'your-key-here'`. No browser is needed for the chat UI itself: open the printed address in your normal browser. Playwright/Chromium are needed only for agent browser tools.

One Groq key can serve both worker and judge when both use Groq. Other model providers or MCP services may need their own credentials or subscriptions. Ollama can run without a hosted model key. The MIT application is free; API usage, compute, and third-party services can cost money.

### Terminal usage

```bash
arena ask --config arena.toml --workspace /absolute/path/to/project \
  --session .arena/my-project --role coder --task "Find the parser bug and fix it"
arena chat --config arena.toml --workspace /absolute/path/to/project --session .arena/my-project
arena ask --config arena.toml --session .arena/design \
  --mode arena --task "Compare alternatives for a small job queue"
```

Reuse the same config, permission flags, workspace path, and session directory across turns. The initial project is copied once; later source-tree edits are not automatically synchronized. Use a new session to import a newer checkout. Original source files are unchanged by built-in tools; inspect `session/workspace` and copy reviewed changes back yourself. There is no automatic git commit, PR publishing, or source merge.

`auto` chooses a single assistant unless the task contains one of these literal phrases: `compare alternatives`, `competing solutions`, `run a tournament`, `use arena`, `debate approaches`. This is a transparent heuristic, not a learned planner. Select `single` or `arena` explicitly when necessary. Arena tournaments keep separate candidate workspaces; their winner is not automatically applied to the persistent assistant workspace.

Roles (`general`, `coder`, `researcher`, `reviewer`) add task instructions; they do not load the ECC plugin or give a model new reasoning abilities. The existing Arena bracket still coordinates competitors, attacks, defenses, and judges.

## What persists

| Path under the session | Purpose |
| --- | --- |
| `source/`, `workspace/` | Initial filtered copy and ongoing working copy |
| `context.sqlite3` | Project text chunks with file/line provenance, and saved successful conversation turns |
| `session.json` | Workspace/config/permission identity |
| `usage.json`, `audit.jsonl` | Single-assistant model request accounting and tool evidence |
| `last-answer.json` | Last completed single-assistant result, usage, workspace, and verification status |
| `artifacts/browser-*.png` | Browser screenshots for the user |
| `tournament-*/` | Independent tournament reports, budgets, patches, and candidate copies |

Project search uses local literal-term ranking, not embeddings. Recent context includes the last four turns, with bounded text. `history_search` retrieves up to three matching turns from the most recent 200. Long histories are not automatically summarized. Context indexing excludes the same credential-like paths as project snapshots, but name filters cannot identify every secret.

`read_document` extracts UTF-8, DOCX text, and PDF text (PDF extra required). Limits: 8 MiB input, first 20 PDF pages, 20,000 output characters. No OCR, image understanding, spreadsheet execution, or rich layout interpretation. Put documents in the copied project and ask the agent to read them. UI attachments accept small text files only; they become task text and may be sent to the model provider.

Single-assistant requests share the session budget across turns. Each Arena tournament has its own configured request/token budget; those counts are in that tournament's report. These are accounting limits, not exact monetary caps. The UI shows model/tool progress events, not token streaming. Closing a tab does not cancel an in-flight job.

## Browser tools

Copy `examples/assistant.toml`, change the model and `browser.origins`, then run:

```bash
arena serve --config examples/assistant.toml --workspace /absolute/path/to/project \
  --session .arena/browser-project --allow-browser
```

Origins are exact scheme/hostname/port tuples; `localhost` and `127.0.0.1` differ. HTTP is permitted only for explicitly configured loopback services. Include the exact HTTPS origins needed for a site and its subresources. Wildcards, embedded credentials, and URL paths are rejected. HTTP redirects are blocked before following the next hop, including same-origin redirects. Directly configure and navigate to the final URL. WebSockets, service workers, and downloads are blocked; streaming sites and complex authentication flows may not work.

Available tools: navigate, snapshot, click, fill, restricted key press, screenshot, list/switch up to four tabs, and inspect bounded console/network evidence. A snapshot returns visible text and element references. The model currently receives text only; screenshots are for human inspection. There is no computer desktop control, iframe/shadow-DOM traversal tool, general file upload, browser-extension support, or CAPTCHA automation.

Each job uses a fresh Chromium context without your normal profile. You can set `headless=false` for a visible window on a laptop. Browser cookies persist only within that job, not across assistant turns. Manual local login may work in a headed context, subject to blocked redirects/origins; reliable persisted authenticated profiles are not implemented.

Click/fill/press require per-action approval in the UI or an interactive terminal. Noninteractive terminal approval is denied. Non-GET/HEAD/OPTIONS browser requests are permitted only during an approved interaction window, then disabled. One approved action can trigger multiple site requests during that bounded window; this is not per-network-request approval. GET endpoints can also have side effects. Treat allowed sites as trusted. The origin policy is an application boundary, not a network sandbox or DNS-pinning firewall. Browser requests do not use `fetch_url`'s public-IP pinning.

## MCP tools

The bridge uses the official MCP Python SDK v1 with persistent stdio or Streamable HTTP sessions for each agent job. It discovers schemas, namespaces tools, validates arguments with JSON Schema, rejects remote schema retrieval, requires explicit tool selection, and asks for approval for configured writes. Prompts/resources, OAuth negotiation, legacy SSE transport, and unsolicited server sampling are not implemented. Remote credentials can be supplied through environment-referenced headers.

A server starts when discovery or a tool listing is requested. That process can have startup side effects even before a tool call. Only configure software/services you trust. Stdio processes are not Docker-sandboxed: they have your OS permissions and may access files/network outside the copied project. A `read_tools` classification is your declaration, not enforcement of a third-party tool's internals. Do not classify a generic arbitrary operation dispatcher as read-only.

```bash
arena mcp-list --config examples/rea.toml --allow-mcp
arena serve --config examples/rea.toml --workspace /absolute/path/to/project \
  --session .arena/rea --allow-mcp
```

First inspect `mcp-list` output, then fill `read_tools` / `write_tools` with exact names the server advertises. A configured but unadvertised name stops the task. At most eight servers, 32 selected tools per server, and 100,000 characters of selected catalog are allowed. Tool names appear as `mcp_rea__<advertised_name>` in the agent's tool list. Responses retain MCP content/structuredContent, and server `isError` results become failed tool evidence. Writes are never automatically retried by the bridge; the server or a future model-requested call can still repeat an action, so inspect external state before approving a retry.

Stdio uses a private `.mcp-home-<server>` next to the workspace plus PATH and explicitly referenced environment variables. It does not automatically forward model keys or normal application login sessions. Processes are still trusted programs, so this is environment hygiene rather than OS isolation. Install Python MCP servers in a virtual environment and use its absolute executable; a package installed only in your user's Python site directory may be unavailable under the private HOME. Explicitly reuse HOME/USERPROFILE only when you want that server to access your existing state. An `npx` command may download code into the private cache on startup; preinstall a reviewed version for offline/reproducible use. HTTP MCP ignores ambient proxy environment settings and uses the configured endpoint directly.

```toml
[[mcp_servers]]
name = "trusted_remote"
url = "https://your-server.example/mcp"
headers = { Authorization = "MY_MCP_AUTHORIZATION" }
read_tools = ["actual_advertised_read_tool"]
write_tools = []
```

Set `MY_MCP_AUTHORIZATION` in your environment to the full header value, such as `Bearer ...`. Config values name environment variables; never paste keys into the TOML.

### API Anything

1. Review [the upstream source and install instructions](https://github.com/goodnight000/api-anything). The inspected version requires Node 22.13+ and a source build; it is not published on npm.
2. Clone it separately, run `npm ci`, pack, and install the produced package following its README. Check that `api-anything` is on PATH, or set the absolute executable in the config. This application does not install it or intercept traffic automatically.
3. Run discovery with `examples/api-anything.toml`. It selects `list_sites`, `list_operations`, `call_operation`, and `login` from the inspected MCP contract. The last two require approval conservatively.
4. Enable `--allow-mcp`. Ask: "List the available sites and operations. Use an existing search operation to research my topic."

The MCP contract calls existing learned operations; teaching a new website requires API Anything's own separate CLI/browser capture workflow. Authenticated sites need deliberate server-side session setup. If you intentionally reuse upstream login state, map HOME to your actual HOME environment variable (Windows may also need USERPROFILE). API Anything's own request/browser tiers and permissions are separate from Arena's browser origin policy.

### REA

The example pins `rea-agents@6.7.0` and launches `mcp`, matching the inspected registration contract. Upstream requires Node 22.19+, 24.11+, or 26+. Review its current installation documentation and provider prerequisites. `npx` must be on PATH (on Windows use the executable/shim form supported by your environment, such as `npx.cmd`). Large binary-analysis providers may exceed the configured 120-second transport limit; narrow the operation or prepare the provider separately.

REA is a reverse-engineering/analysis toolkit, not a normal Canva/YouTube task assistant. It can inspect supported local JavaScript apps, binaries, and saved network captures. Start with a copied local project you own or are authorized to analyze. Discovery is enabled but no REA tools are selected by default: choose exact names and read/write classifications after inspecting the schema. Some providers require installed software, licenses, processes, or explicit environment variables. This bridge does not install providers or automatically execute REA's skill instructions.

## Execution, UI, and limits

Code execution still requires `--allow-exec` and Docker; there is no unrestricted host-shell tool. Configure `verify_argv` and a trusted image with dependencies installed. The configured verification command runs independently of the model's claims. Without checks, answers remain `needs_review`. Built-in file and Docker restrictions do not apply to external MCP servers.

The UI listens on IPv4 loopback only, validates Host/Origin, requires a per-process CSRF token for POST, disallows concurrent jobs, and serializes action approvals. Do not expose it through a public reverse proxy. It is a local development interface, not a multi-user authenticated service. Answers and attachments render as plain text. Credentials stay in the process environment, but task/source/tool evidence can go to configured model providers and session logs; inspect projects and server access accordingly.

This release closes several tool gaps, not model-quality gaps. It has no guarantee of parity with Claude Code/ChatGPT, universal model compatibility, autonomous long-running background tasks, automatic internet search provider, voice/video capabilities, or full desktop control. Use a capable model, meaningful verification, and inspect results.
