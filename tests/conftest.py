"""Shared test fixtures for eagle-mcp.

server.py reads its base URL / token once at import time (`_load_creds()`),
so tests that care about that behavior need a fresh import with a controlled
environment. `load_server()` below does that: it clears the relevant env
vars, applies whatever the test wants, points `Path.home()` at a temp dir
(so a real `~/.config/eagle/eagle.env` on the machine running the tests can
never leak in), and re-imports the module.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ENV_KEYS = ("EAGLE_BRIDGE_URL", "EAGLE_BRIDGE_TOKEN")


def load_server(monkeypatch, tmp_path, *, env: dict | None = None, config_env: dict | None = None):
    """Import (or re-import) server.py with a controlled credential environment.

    env: values to set as real environment variables (highest precedence).
    config_env: if given, written as ~/.config/eagle/eagle.env (home() is
    redirected to tmp_path so this never touches the real machine).
    """
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    if env:
        for k, v in env.items():
            monkeypatch.setenv(k, v)

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    if config_env:
        cfg_dir = tmp_path / ".config" / "eagle"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        lines = [f'{k}="{v}"' for k, v in config_env.items()]
        (cfg_dir / "eagle.env").write_text("\n".join(lines) + "\n")

    sys.modules.pop("server", None)
    return importlib.import_module("server")


@pytest.fixture
def server(monkeypatch, tmp_path):
    """server.py imported fresh with a known, fake bridge URL + token."""
    return load_server(
        monkeypatch,
        tmp_path,
        env={"EAGLE_BRIDGE_URL": "https://bridge.test", "EAGLE_BRIDGE_TOKEN": "test-token"},
    )
