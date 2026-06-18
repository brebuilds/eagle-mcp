# eagle-mcp

Native MCP tools for Claude + agents over the **Eagle Bridge** on `veggie`
(tailnet-only POD asset service). Wraps the bridge HTTP API so any Claude
session can push/pull/tag/process design assets — without ever handling the
bridge token in a prompt.

## Tools

| Tool | What it does |
|------|--------------|
| `eagle_health` | Bridge reachable + Eagle app connected (`{ok, eagle, recipes}`) |
| `eagle_product_types` | Print recipes (tee/sticker/mug + dims/dpi/bleed/upscale) |
| `eagle_list_assets` | Search library by `query` / `brand` / `tag` |
| `eagle_get_asset` | Full metadata for one Eagle item id |
| `eagle_ingest_url` | Ingest a design from a URL (no auto-tag) |
| `eagle_ingest_file` | Upload a local file (triggers vision **auto-tag** on ingest) |
| `eagle_tag_asset` | Add workflow/subject tags |
| `eagle_process_asset` | Print-ready resize/bleed/sRGB/upscale per product type |
| `eagle_autotag` | Enqueue async vision auto-tag for an existing asset |
| `eagle_autotag_status` | Auto-tag queue status |

## Credentials

The server reads, in order of precedence:
1. env vars `EAGLE_BRIDGE_URL` / `EAGLE_BRIDGE_TOKEN`
2. `~/.config/eagle/eagle.env` (KEY=VALUE, chmod 600) — **default**

The token is never stored in this repo.

## Setup

```bash
uv venv --python 3.13 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
```

## Register in Claude Code (user scope = all projects)

```bash
claude mcp add eagle --scope user -- \
  /Users/bre/eagle-mcp/.venv/bin/python /Users/bre/eagle-mcp/server.py
```

Restart the Claude session to load the tools. Verify with `claude mcp list`.

## Run / debug standalone

```bash
.venv/bin/python server.py                       # stdio
npx @modelcontextprotocol/inspector .venv/bin/python server.py   # interactive
```

## Follow-up

Register in the always-on `mcp-hub` on **h64** so OpenClaw/SPARKY agents get
the same tools (their token lives server-side on h64).
