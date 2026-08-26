"""Tests for eagle-mcp's server.py.

Since server.py is a thin client, these tests cover exactly what a thin
client can get wrong: tool schemas are well-formed, requests are built with
the right method/path/body/params, auth headers are attached correctly, and
HTTP/timeout/connect errors are turned into readable messages instead of
raw exceptions.

`respx` mocks httpx at the transport level, so `_client()`'s per-call
`httpx.Client(...)` instances are all intercepted the same way.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import respx

from conftest import load_server

BASE = "https://bridge.test"


# ---------------------------------------------------------------------------
# Tool schema validity
# ---------------------------------------------------------------------------

def test_all_ten_tools_are_registered_with_valid_schemas(server):
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "eagle_health",
        "eagle_product_types",
        "eagle_list_assets",
        "eagle_get_asset",
        "eagle_ingest_url",
        "eagle_ingest_file",
        "eagle_tag_asset",
        "eagle_process_asset",
        "eagle_autotag",
        "eagle_autotag_status",
    }
    for t in tools:
        assert t.description, f"{t.name} has no description"
        assert t.inputSchema.get("type") == "object"
        assert "properties" in t.inputSchema


def test_eagle_tag_asset_schema_has_add_and_remove_not_tags(server):
    # Locks in the fixed contract: the tool's own schema should offer add/remove,
    # matching what the bridge route actually reads (body.add / body.remove).
    tools = asyncio.run(server.mcp.list_tools())
    tag_tool = next(t for t in tools if t.name == "eagle_tag_asset")
    props = tag_tool.inputSchema["properties"]
    assert "add" in props
    assert "remove" in props
    assert "tags" not in props


# ---------------------------------------------------------------------------
# The bug: eagle_tag_asset must send {add, remove}, not a bare {tags}
# ---------------------------------------------------------------------------

@respx.mock
def test_eagle_tag_asset_sends_add_remove_body(server):
    route = respx.post(f"{BASE}/api/assets/ITEM1/tags").mock(
        return_value=httpx.Response(200, json={"id": "ITEM1", "tags": ["ready"]})
    )
    server.eagle_tag_asset("ITEM1", add=["ready"], remove=["new"])
    assert route.called
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body == {"add": ["ready"], "remove": ["new"]}
    assert "tags" not in sent_body


@respx.mock
def test_eagle_tag_asset_defaults_missing_side_to_empty_list(server):
    route = respx.post(f"{BASE}/api/assets/ITEM1/tags").mock(
        return_value=httpx.Response(200, json={"id": "ITEM1", "tags": []})
    )
    server.eagle_tag_asset("ITEM1", add=["ready"])
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body == {"add": ["ready"], "remove": []}


# ---------------------------------------------------------------------------
# Request building for the other tools
# ---------------------------------------------------------------------------

@respx.mock
def test_eagle_health_hits_the_right_path(server):
    route = respx.get(f"{BASE}/api/health").mock(
        return_value=httpx.Response(200, json={"ok": True, "eagle": True, "recipes": 3})
    )
    out = server.eagle_health()
    assert route.called
    assert '"ok": true' in out.lower()


@respx.mock
def test_eagle_list_assets_only_sends_provided_params(server):
    route = respx.get(f"{BASE}/api/assets").mock(return_value=httpx.Response(200, json=[]))
    server.eagle_list_assets(brand="ORB")
    assert route.called
    sent = route.calls[0].request.url.params
    assert dict(sent) == {"brand": "ORB"}


@respx.mock
def test_eagle_list_assets_sends_all_three_params_when_given(server):
    route = respx.get(f"{BASE}/api/assets").mock(return_value=httpx.Response(200, json=[]))
    server.eagle_list_assets(query="skull", brand="ORB", tag="ready")
    sent = route.calls[0].request.url.params
    assert dict(sent) == {"q": "skull", "brand": "ORB", "tag": "ready"}


@respx.mock
def test_eagle_get_asset_uses_the_id_in_the_path(server):
    route = respx.get(f"{BASE}/api/assets/ITEM42").mock(
        return_value=httpx.Response(200, json={"item": {"id": "ITEM42"}})
    )
    server.eagle_get_asset("ITEM42")
    assert route.called


@respx.mock
def test_eagle_ingest_url_omits_optional_fields_when_not_given(server):
    route = respx.post(f"{BASE}/api/assets").mock(
        return_value=httpx.Response(201, json={"id": "ITEM1"})
    )
    server.eagle_ingest_url("https://example.com/a.png", "ORB")
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body == {"url": "https://example.com/a.png", "brand": "ORB"}


@respx.mock
def test_eagle_ingest_url_includes_optional_fields_when_given(server):
    route = respx.post(f"{BASE}/api/assets").mock(
        return_value=httpx.Response(201, json={"id": "ITEM1"})
    )
    server.eagle_ingest_url(
        "https://example.com/a.png", "ORB", airtable_design_id="rec1", tags=["new"]
    )
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body == {
        "url": "https://example.com/a.png",
        "brand": "ORB",
        "airtableDesignId": "rec1",
        "tags": ["new"],
    }


def test_eagle_ingest_file_reports_missing_file_without_a_network_call(server):
    out = server.eagle_ingest_file("/definitely/not/a/real/path.png", "ORB")
    assert out.startswith("ERROR")
    assert "not found" in out


@respx.mock
def test_eagle_process_asset_sends_types(server):
    route = respx.post(f"{BASE}/api/assets/ITEM1/process").mock(
        return_value=httpx.Response(200, json={"processed": {}})
    )
    server.eagle_process_asset("ITEM1", ["tee", "mug"])
    sent_body = json.loads(route.calls[0].request.content)
    assert sent_body == {"types": ["tee", "mug"]}


@respx.mock
def test_eagle_autotag_status_is_a_get(server):
    route = respx.get(f"{BASE}/api/autotag/status").mock(
        return_value=httpx.Response(200, json={"pending": 0, "current": None})
    )
    server.eagle_autotag_status()
    assert route.called
    assert route.calls[0].request.method == "GET"


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------

@respx.mock
def test_bearer_header_is_attached_when_token_present(server):
    route = respx.get(f"{BASE}/api/health").mock(return_value=httpx.Response(200, json={}))
    server.eagle_health()
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_no_authorization_header_when_token_is_blank(monkeypatch, tmp_path):
    srv = load_server(
        monkeypatch, tmp_path, env={"EAGLE_BRIDGE_URL": BASE, "EAGLE_BRIDGE_TOKEN": ""}
    )
    route = respx.get(f"{BASE}/api/health").mock(return_value=httpx.Response(200, json={}))
    srv.eagle_health()
    assert "Authorization" not in route.calls[0].request.headers


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------

@respx.mock
def test_non_2xx_response_is_formatted_as_error(server):
    respx.get(f"{BASE}/api/health").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    out = server.eagle_health()
    assert out.startswith("ERROR 500")
    assert "boom" in out


@respx.mock
def test_timeout_is_turned_into_a_readable_message(server):
    respx.get(f"{BASE}/api/health").mock(side_effect=httpx.TimeoutException("slow"))
    out = server.eagle_health()
    assert out.startswith("ERROR")
    assert "timed out" in out


@respx.mock
def test_connect_error_is_turned_into_a_readable_message(server):
    respx.get(f"{BASE}/api/health").mock(side_effect=httpx.ConnectError("nope"))
    out = server.eagle_health()
    assert out.startswith("ERROR")
    assert "cannot reach" in out
    assert BASE in out


# ---------------------------------------------------------------------------
# Credential loading precedence
# ---------------------------------------------------------------------------

def test_env_vars_take_precedence_over_config_file(monkeypatch, tmp_path):
    srv = load_server(
        monkeypatch,
        tmp_path,
        env={"EAGLE_BRIDGE_URL": "https://from-env.test", "EAGLE_BRIDGE_TOKEN": "env-token"},
        config_env={"EAGLE_BRIDGE_URL": "https://from-file.test", "EAGLE_BRIDGE_TOKEN": "file-token"},
    )
    assert srv.BASE_URL == "https://from-env.test"
    assert srv.TOKEN == "env-token"


def test_falls_back_to_config_file_when_env_vars_absent(monkeypatch, tmp_path):
    srv = load_server(
        monkeypatch,
        tmp_path,
        config_env={"EAGLE_BRIDGE_URL": "https://from-file.test", "EAGLE_BRIDGE_TOKEN": "file-token"},
    )
    assert srv.BASE_URL == "https://from-file.test"
    assert srv.TOKEN == "file-token"


def test_defaults_to_localhost_when_nothing_is_configured(monkeypatch, tmp_path):
    srv = load_server(monkeypatch, tmp_path)
    assert srv.BASE_URL == "http://localhost:3110"
    assert srv.TOKEN == ""
