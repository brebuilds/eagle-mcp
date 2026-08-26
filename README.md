# eagle-mcp

Native MCP tools for Claude (and other agents) over the
[eagle-bridge](https://github.com/brebuilds/eagle-bridge) HTTP API — a service that turns
the [Eagle](https://eagle.cool) design-asset manager into a shared, network-reachable
print-on-demand asset store. This repo wraps that API so a Claude session can
push/pull/tag/process design assets without ever handling the bridge's bearer token in a
prompt.

## Why this exists

It's deliberately a thin client. All the actual logic — print-ready image processing,
vision auto-tagging, the Airtable link, recipe management — lives in `eagle-bridge`. This
repo's only job is to expose that HTTP API as ten MCP tools with clear docstrings, so an
agent gets a natural-language-friendly interface instead of having to construct raw HTTP
calls (and, more importantly, without needing to be handed the bridge token to do it — the
token lives only in this process's environment or its config file, never in a prompt).

If you're looking for the interesting engineering — the upscale math, the sRGB/bleed/DPI
handling, the auto-tag queue — that's in
[eagle-bridge's README](https://github.com/brebuilds/eagle-bridge#architecture). This one's
short on purpose.

## Architecture

```
Claude / agent ──(MCP tool call)──► server.py ──(HTTP, Bearer token)──► eagle-bridge ──► Eagle / Airtable / Ollama
```

`server.py` is ~230 lines: 10 `@mcp.tool()`-decorated functions, a shared `httpx.Client`
factory (`_client()`) that attaches the bearer token and picks a timeout (a long one for the
process/upscale tools, since those can take a while), and a response formatter that turns a
non-2xx response or a timeout/connect error into a readable string instead of a raw
exception.

## Tools

| Tool | What it does |
|------|--------------|
| `eagle_health` | Bridge reachable + Eagle app connected (`{ok, eagle, recipes}`) |
| `eagle_product_types` | Print recipes (tee/sticker/mug + dims/dpi/bleed/upscale) |
| `eagle_list_assets` | Search library by `query` / `brand` / `tag` |
| `eagle_get_asset` | Full metadata for one Eagle item id |
| `eagle_ingest_url` | Ingest a design from a URL (no auto-tag) |
| `eagle_ingest_file` | Upload a local file (triggers vision **auto-tag** on ingest) |
| `eagle_tag_asset` | Add and/or remove workflow/subject tags (`add`, `remove`) |
| `eagle_process_asset` | Print-ready resize/bleed/sRGB/upscale per product type |
| `eagle_autotag` | Enqueue async vision auto-tag for an existing asset |
| `eagle_autotag_status` | Auto-tag queue status |

## Credentials

The server reads, in order of precedence:
1. env vars `EAGLE_BRIDGE_URL` / `EAGLE_BRIDGE_TOKEN`
2. `~/.config/eagle/eagle.env` (KEY=VALUE, chmod 600)
3. falls back to `http://localhost:3110` with no token if neither is set

The token is never stored in this repo.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
EAGLE_BRIDGE_URL=http://localhost:3110 EAGLE_BRIDGE_TOKEN=... .venv/bin/python server.py   # stdio
```

Or interactively:

```bash
npx @modelcontextprotocol/inspector .venv/bin/python server.py
```

### Register with Claude Code

```bash
claude mcp add eagle --scope user -- \
  /path/to/eagle-mcp/.venv/bin/python /path/to/eagle-mcp/server.py
```

Restart the Claude session to load the tools; verify with `claude mcp list`.

## Tests

**21 tests, all passing**, `httpx` mocked via `respx` — no live bridge required:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest -q
```

Coverage: all 10 tools are registered with valid MCP schemas, request building (method,
path, query params, JSON body, which optional fields get omitted vs. sent) for every tool,
the bearer-auth header is attached when a token is present and omitted when it's blank,
timeout/connect/non-2xx errors are turned into readable messages, and the credential-loading
precedence (env vars > config file > default).

## A real integration bug this repo found

Early on, `eagle_tag_asset` sent:

```python
c.post(f"/api/assets/{asset_id}/tags", json={"tags": tags})
```

but `eagle-bridge`'s route (`src/routes/assets.ts`) reads:

```ts
const item = await svc.setTags(c.req.param("id"), body.add ?? [], body.remove ?? []);
```

Neither side was malformed — they were both internally consistent, and both had tests that
passed. The bridge's route had **no test at all** for that endpoint, and this repo had **no
tests for anything**. The bug was a pure contract mismatch across the two repos: the client
sent a `tags` key the server never read, so `body.add` and `body.remove` were always
undefined, defaulted to `[]`, and the call updated the asset with **zero tag changes**. The
request returned `200 OK` with a normal-looking response body. Nothing about a single
request, in isolation, looked wrong.

It was only findable by tracing the actual contract across both repos — reading the request
one side sends and the body the other side reads, side by side — not by testing either repo
alone.

**Fix:** `eagle_tag_asset` now takes `add`/`remove` (matching the bridge's shape, which is
strictly more expressive than a bare replace-list — you can add and remove tags in one
call), and sends `{"add": [...], "remove": [...]}`. Both repos now have direct regression
coverage: this repo's `test_eagle_tag_asset_sends_add_remove_body` asserts the exact JSON
body sent, and `eagle-bridge`'s `tests/routes.test.ts` gained a same-behavior test plus one
that documents what a bare `{"tags": [...]}` body actually does today (nothing) — so if this
contract drifts again, at least one side will fail loudly instead of returning a quiet 200.

## Known limitations

- **No auth beyond the bearer token the bridge itself enforces.** This client trusts
  whatever `EAGLE_BRIDGE_URL` points at; it does no certificate pinning or host allow-listing.
- **No retries.** A timeout or connect error is reported back as a readable string, not
  retried — the caller (the agent, or the human reading the tool output) decides whether to
  try again.
- **`eagle_ingest_file` reads the whole file into the multipart request in memory** — fine
  for POD-sized design files, not meant for large video/archives.
- **This repo has no opinion about what a "brand" is** — brand names are just strings passed
  through to the bridge, which owns the actual brand/keyword configuration
  (`eagle-bridge/src/autotag/brands.ts`).

## Related

[`eagle-bridge`](https://github.com/brebuilds/eagle-bridge) is the actual service this repo
is a client for — read its README for the print-prep pipeline, the auto-tag queue, and the
architecture behind these ten tools.
