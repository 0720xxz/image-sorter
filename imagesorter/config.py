"""Tiny JSON settings store (no registry, no external dependency)."""

from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".image-sorter.json"

DEFAULTS = {
    "source": "",
    "target": "",
    "same": False,
    "mode": "move",
    "layout": "{YYYY}-{MM}",
    "recursive": True,
    "fallback": "auto",
    "conflict": "rename",
    "rename_files": True,
    "prune_empty": False,
    "delete_duplicates": False,
}


def load_settings() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
            stored = json.load(handle)
        if isinstance(stored, dict):
            for key in DEFAULTS:
                if key in stored:
                    data[key] = stored[key]
    except (OSError, ValueError):
        pass
    return data


def save_settings(data: dict) -> None:
    payload = {key: data.get(key, DEFAULTS[key]) for key in DEFAULTS}
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        pass
