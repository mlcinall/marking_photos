from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_COMPONENT = components.declare_component(
    "keyboard_listener",
    path=str((Path(__file__).resolve().parent / "keyboard_component")),
)


def listen_hotkeys(enabled: bool = True, key: str = "keyboard_listener") -> str | None:
    payload = _COMPONENT(enabled=enabled, key=key, default=None)
    if isinstance(payload, dict):
        return payload.get("action")
    return None
