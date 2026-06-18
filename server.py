#!/usr/bin/env python3
"""Eagle MCP server — native Claude/agent tools over the Eagle Bridge on veggie.

Thin wrapper around the tailnet-only Eagle Bridge HTTP API (push/pull/tag/process
POD design assets, link to Airtable). Auth via a Bearer token that lives ONLY
server-side here — agents call the tools, never handle the secret.

Creds (in order of precedence):
  1. env vars EAGLE_BRIDGE_URL / EAGLE_BRIDGE_TOKEN
  2. ~/.config/eagle/eagle.env  (KEY=VALUE, chmod 600)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config / credentials
# ---------------------------------------------------------------------------

def _load_creds() -> tuple[str, str]:
    url = os.environ.get("EAGLE_BRIDGE_URL")
    token = os.environ.get("EAGLE_BRIDGE_TOKEN")

    env_file = Path.home() / ".config" / "eagle" / "eagle.env"
    if (not url or not token) and env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k == "EAGLE_BRIDGE_URL" and not url:
                url = v
            elif k == "EAGLE_BRIDGE_TOKEN" and not token:
                token = v

    url = (url or "https://vegetablelappy.taild64ac4.ts.net").rstrip("/")
    return url, (token or "")


BASE_URL, TOKEN = _load_creds()

# Generous timeouts: veggie can be asleep (~8s cold); image processing/upscale
# can take much longer than a normal request, so those tools override below.
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=15.0)
_LONG_TIMEOUT = httpx.Timeout(300.0, connect=15.0)


def _client(timeout: httpx.Timeout = _DEFAULT_TIMEOUT) -> httpx.Client:
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return httpx.Client(base_url=BASE_URL, headers=headers, timeout=timeout)


def _result(resp: httpx.Response) -> str:
    """Format an HTTP response into a readable tool result."""
    ok = resp.is_success
    try:
        body = resp.json()
        body_text = json.dumps(body, indent=2, ensure_ascii=False)
    except Exception:
        body_text = resp.text
    if ok:
        return body_text
    return f"ERROR {resp.status_code} {resp.reason_phrase}\n{body_text}"


def _err(e: Exception) -> str:
    if isinstance(e, httpx.TimeoutException):
        return ("ERROR: request to the Eagle bridge timed out. veggie may be "
                "asleep or the bridge is down — check the Eagle card on the "
                "command-centre, then retry.")
    if isinstance(e, httpx.ConnectError):
        return ("ERROR: cannot reach the Eagle bridge. Confirm this machine is "
                f"on the tailnet and {BASE_URL} is up.")
    return f"ERROR: {type(e).__name__}: {e}"


mcp = FastMCP("eagle")

# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

@mcp.tool()
def eagle_health() -> str:
    """Check the Eagle bridge: is it reachable and is the Eagle app connected.

    Returns {ok, eagle, recipes}. eagle=true means the Eagle app on veggie is
    up and writes will work. Use this first if other tools are failing.
    """
    try:
        with _client() as c:
            return _result(c.get("/api/health"))
    except Exception as e:
        return _err(e)


@mcp.tool()
def eagle_product_types() -> str:
    """List the configured POD product types / print recipes (tee, sticker, mug,
    ...) with their print dimensions, dpi, fit, bleed, and upscale settings.

    These are the valid `types` values for eagle_process_asset.
    """
    try:
        with _client() as c:
            return _result(c.get("/api/product-types"))
    except Exception as e:
        return _err(e)


@mcp.tool()
def eagle_list_assets(
    query: Optional[str] = None,
    brand: Optional[str] = None,
    tag: Optional[str] = None,
) -> str:
    """Search the Eagle design library.

    Args:
        query: free-text search across asset name/tags.
        brand: filter by brand folder (TFH, Coastly, OIB.Guide, Funky Legs,
            Design & Chill).
        tag: filter by a workflow/state tag (new, ready, listed, archived) or
            any subject/style tag.
    """
    params = {}
    if query:
        params["q"] = query
    if brand:
        params["brand"] = brand
    if tag:
        params["tag"] = tag
    try:
        with _client() as c:
            return _result(c.get("/api/assets", params=params))
    except Exception as e:
        return _err(e)


@mcp.tool()
def eagle_get_asset(asset_id: str) -> str:
    """Get one Eagle asset's full metadata (name, tags, folders, dimensions,
    annotation/Airtable link, processed outputs) by its Eagle item id."""
    try:
        with _client() as c:
            return _result(c.get(f"/api/assets/{asset_id}"))
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------------------
# Write tools (create / mutate)
# ---------------------------------------------------------------------------

@mcp.tool()
def eagle_ingest_url(
    url: str,
    brand: str,
    airtable_design_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """Ingest a design into Eagle from a URL.

    NOTE: URL ingest does NOT auto-tag (no local original). For vision
    auto-tagging on ingest, use eagle_ingest_file with local bytes.

    Args:
        url: public/tailnet URL of the image to pull in.
        brand: brand folder to file it under (TFH, Coastly, ...).
        airtable_design_id: optional Airtable Designs record id to back-link.
        tags: optional list of tags to apply.
    """
    body: dict = {"url": url, "brand": brand}
    if airtable_design_id:
        body["airtableDesignId"] = airtable_design_id
    if tags:
        body["tags"] = tags
    try:
        with _client() as c:
            return _result(c.post("/api/assets", json=body))
    except Exception as e:
        return _err(e)


@mcp.tool()
def eagle_ingest_file(
    file_path: str,
    brand: str,
    airtable_design_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> str:
    """Ingest a design into Eagle by uploading a local file (multipart).

    This is the path that triggers vision auto-tagging on ingest (SEO/subject/
    style/colors). Prefer this over eagle_ingest_url when the file is on disk.

    Args:
        file_path: absolute path to the image file on this machine.
        brand: brand folder to file it under.
        airtable_design_id: optional Airtable Designs record id to back-link.
        tags: optional list of tags to apply in addition to auto-tags.
    """
    p = Path(file_path).expanduser()
    if not p.is_file():
        return f"ERROR: file not found: {p}"
    data: dict = {"brand": brand}
    if airtable_design_id:
        data["airtableDesignId"] = airtable_design_id
    if tags:
        # repeat the field so Hono parses a list
        data_tags = [("tags", t) for t in tags]
    else:
        data_tags = []
    try:
        with _client(_LONG_TIMEOUT) as c, p.open("rb") as fh:
            files = {"file": (p.name, fh)}
            form = list(data.items()) + data_tags
            return _result(c.post("/api/assets", data=form, files=files))
    except Exception as e:
        return _err(e)


@mcp.tool()
def eagle_tag_asset(asset_id: str, tags: list[str]) -> str:
    """Add workflow/subject tags to an existing Eagle asset.

    Args:
        asset_id: Eagle item id.
        tags: tags to add (e.g. ["ready", "listed"]).
    """
    try:
        with _client() as c:
            return _result(c.post(f"/api/assets/{asset_id}/tags", json={"tags": tags}))
    except Exception as e:
        return _err(e)


@mcp.tool()
def eagle_process_asset(asset_id: str, types: list[str]) -> str:
    """Run print-ready image processing for one or more product types.

    Resizes/bleeds/sRGB-normalizes (and upscales) the asset per each product
    type's recipe. Can take a while for large upscales.

    Args:
        asset_id: Eagle item id.
        types: product type keys from eagle_product_types (e.g. ["tee",
            "sticker", "mug"]).
    """
    try:
        with _client(_LONG_TIMEOUT) as c:
            return _result(c.post(f"/api/assets/{asset_id}/process", json={"types": types}))
    except Exception as e:
        return _err(e)


@mcp.tool()
def eagle_autotag(asset_id: str) -> str:
    """Enqueue async vision auto-tagging for an asset already in the library
    (SEO + subject + style + colors). Returns immediately (202); poll
    eagle_autotag_status for progress."""
    try:
        with _client() as c:
            return _result(c.post(f"/api/assets/{asset_id}/autotag"))
    except Exception as e:
        return _err(e)


@mcp.tool()
def eagle_autotag_status() -> str:
    """Get the auto-tagging queue status ({pending, current})."""
    try:
        with _client() as c:
            return _result(c.get("/api/autotag/status"))
    except Exception as e:
        return _err(e)


if __name__ == "__main__":
    mcp.run()
