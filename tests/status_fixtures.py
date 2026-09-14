"""Restore the preserved Phase 2 selectors for its historical mutation contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def restore_phase2_selectors(root: Path) -> None:
    archive = json.loads(
        (ROOT / "docs/implementation/evidence/phase-3-start-d2ebdaf.json").read_bytes()
    )
    for name in ("PROJECT_STATUS.json", "PROJECT_PROGRESS.json"):
        document: dict[str, Any] = json.loads((root / name).read_bytes())
        for observation in archive["observations"]:
            if observation["document"] != name:
                continue
            keys = observation["pointer"].strip("/").split("/")
            parent = document
            for key in keys[:-1]:
                parent = parent[key]
            parent[keys[-1]] = observation["value"]
        for pointer in archive["added_pointers"][name]:
            keys = pointer.strip("/").split("/")
            parent = document
            for key in keys[:-1]:
                parent = parent[key]
            parent.pop(keys[-1], None)
        (root / name).write_text(json.dumps(document), encoding="utf-8")
