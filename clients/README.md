# Connect any AI tool / CLI to your Brain

Templates for pointing MCP-capable AI clients at a running Company Brain. Each
file is the config for one tool — replace the placeholders and drop it in.

Replace in every file:
- `https://YOUR_BRAIN_HOST` → your brain's base URL (e.g. `https://brain.example.com`)
- `<YOUR_API_KEY>` → an API key from `BRAIN_API_KEYS` (give each tool its own key so
  `GET /activity?who=<agent>` stays attributable)
- `BRAIN_VERIFY_TLS` → `true` with a real cert; `false` only for a self-signed / IP cert
- `command` is `brain-mcp` (install the connector first: `pip install -e .` from this repo,
  which provides the `brain-mcp` command). On Windows you can use the full path to
  `brain-mcp.exe` instead.

## Where each file goes

| Tool | File | Destination |
|------|------|-------------|
| Claude Code | use `claude mcp add` (see below) | `~/.claude.json` |
| Claude Desktop | `claude_desktop_config.json` | `%APPDATA%\Claude\claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`) |
| Cursor | `cursor_mcp.json` | `~/.cursor/mcp.json` |
| Windsurf | `windsurf_mcp_config.json` | `~/.codeium/windsurf/mcp_config.json` |
| VS Code | `vscode_mcp.json` | `.vscode/mcp.json` |
| OpenCode | `opencode.json` | `~/.config/opencode/opencode.json` or project `opencode.json` |
| Gemini CLI | `gemini_settings.json` | `~/.gemini/settings.json` |
| Qwen Code CLI | `qwen_settings.json` | `~/.qwen/settings.json` |
| GitHub Copilot CLI | `github_copilot_mcp-config.json` | `~/.copilot/mcp-config.json` |
| JetBrains (AI Assistant/Junie) | `jetbrains_mcp.json` | Settings → AI Assistant → MCP → Add → As JSON |
| Zed | `zed_settings.json` | merge `context_servers` into Zed `settings.json` |
| Devin / cloud agents | `devin_REST.md` | REST API (no local stdio connector) |

Config shapes differ on purpose: `mcpServers` (most), `mcp` (OpenCode),
`servers` (VS Code), `context_servers` (Zed), REST (Devin).

## Claude Code (one command)
```bash
claude mcp add company-brain brain-mcp -s user \
  -e BRAIN_URL=https://YOUR_BRAIN_HOST \
  -e BRAIN_API_KEY=<YOUR_API_KEY> \
  -e BRAIN_AGENT=claude-code \
  -e BRAIN_PROJECT=default \
  -e BRAIN_VERIFY_TLS=true
```

## Verify the connection
```bash
brain-mcp --check
```
Uses the same `BRAIN_URL` / `BRAIN_API_KEY` / `BRAIN_VERIFY_TLS` settings as the
connector: prints `PASS` with the server version, or `FAIL` naming the missing
env var / error. Exit code 0/1, so it also works in scripts.

## Auto-capture (optional)
`hooks/brain_autosave.py` is a Claude Code `Stop` hook that ingests each finished
exchange into the brain automatically. See the header of that file to wire it up.
