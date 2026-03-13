from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def default_session() -> dict[str, Any]:
    return {
        "dataset_root": "",
        "listings": [],
        "labels": {},
        "actions": [],
        "photo_cursor": {},
        "current_listing_id": None,
    }


def load_session(session_path: Path) -> dict[str, Any]:
    if not session_path.exists():
        return default_session()
    try:
        with session_path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (json.JSONDecodeError, OSError):
        return default_session()

    state = default_session()
    state.update(data)
    return state


def save_session(session_path: Path, session_data: dict[str, Any]) -> None:
    with session_path.open("w", encoding="utf-8") as fp:
        json.dump(session_data, fp, ensure_ascii=False, indent=2)


def save_results_csv(csv_path: Path, labels: dict[str, int], listings: list[dict[str, Any]]) -> None:
    listing_lookup = {item["listing_id"]: item for item in listings}

    with csv_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["listing_id", "shown_photo_indices", "label"])
        writer.writeheader()

        for listing_id in sorted(labels.keys()):
            listing = listing_lookup.get(listing_id)
            if not listing:
                continue
            writer.writerow(
                {
                    "listing_id": listing_id,
                    "shown_photo_indices": json.dumps(listing["shown_indices"], ensure_ascii=False),
                    "label": labels[listing_id],
                }
            )
