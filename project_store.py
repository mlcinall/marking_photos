from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_VERSION = 2
ALLOWED_LABELS = {0, 1, 2}


@dataclass
class ProjectMetadata:
    project_id: str
    project_name: str
    source_zip_name: str
    imported_at: str
    root_mode: str
    total_listing_folders: int
    valid_listings: int
    skipped_listings: int


@dataclass
class ProjectPaths:
    root: Path
    extracted: Path
    logs: Path
    state_file: Path
    results_csv: Path
    metadata_file: Path


class StateValidationError(ValueError):
    pass


def ensure_data_layout(base_dir: Path) -> Path:
    projects_dir = base_dir / "data" / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    return projects_dir


def project_paths(project_dir: Path) -> ProjectPaths:
    return ProjectPaths(
        root=project_dir,
        extracted=project_dir / "extracted",
        logs=project_dir / "logs",
        state_file=project_dir / "session_state.json",
        results_csv=project_dir / "results.csv",
        metadata_file=project_dir / "metadata.json",
    )


def atomic_write_text(path: Path, data: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fp:
            fp.write(data)
            fp.flush()
            os.fsync(fp.fileno())
        Path(tmp_name).replace(path)
    finally:
        if Path(tmp_name).exists():
            Path(tmp_name).unlink(missing_ok=True)


def atomic_write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            fp.flush()
            os.fsync(fp.fileno())
        Path(tmp_name).replace(path)
    finally:
        if Path(tmp_name).exists():
            Path(tmp_name).unlink(missing_ok=True)


def default_state(project_id: str = "") -> dict[str, Any]:
    return {
        "state_version": STATE_VERSION,
        "project_id": project_id,
        "dataset_root": "",
        "listings": [],
        "labels": {},
        "actions": [],
        "photo_cursor": {},
        "viewed_indices": {},
        "current_listing_id": None,
        "mode": "labeling",
        "warnings": [],
    }


def validate_state(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not isinstance(raw, dict):
        raise StateValidationError("State file is not a JSON object")

    version = raw.get("state_version", 1)
    if not isinstance(version, int):
        raise StateValidationError("state_version must be integer")

    state = default_state(str(raw.get("project_id", "")))
    state.update(raw)
    state["state_version"] = version

    if version < STATE_VERSION:
        warnings.append(f"State migrated from v{version} to v{STATE_VERSION}")
        state["state_version"] = STATE_VERSION
        state.setdefault("viewed_indices", {})
        state.setdefault("mode", "labeling")
    elif version > STATE_VERSION:
        warnings.append(
            f"State version {version} is newer than supported {STATE_VERSION}. Some fields may be ignored."
        )

    required_list = ["listings", "actions"]
    for key in required_list:
        if not isinstance(state.get(key), list):
            raise StateValidationError(f"Field '{key}' must be a list")

    required_dict = ["labels", "photo_cursor", "viewed_indices"]
    for key in required_dict:
        if not isinstance(state.get(key), dict):
            raise StateValidationError(f"Field '{key}' must be a dict")

    cleaned_listings = []
    for listing in state["listings"]:
        if not isinstance(listing, dict):
            warnings.append("Invalid listing entry skipped")
            continue
        expected = {"listing_id", "directory", "shown_indices", "shown_files"}
        if not expected.issubset(set(listing.keys())):
            warnings.append(f"Listing entry skipped due to missing fields: {listing}")
            continue
        cleaned_listings.append(listing)
    state["listings"] = cleaned_listings

    valid_ids = {item["listing_id"] for item in cleaned_listings}
    cleaned_labels = {}
    for lid, label in state["labels"].items():
        if lid in valid_ids and label in ALLOWED_LABELS:
            cleaned_labels[lid] = int(label)
    state["labels"] = cleaned_labels

    state["photo_cursor"] = {
        lid: int(idx) for lid, idx in state["photo_cursor"].items() if lid in valid_ids and isinstance(idx, int)
    }

    viewed: dict[str, list[int]] = {}
    for lid, indices in state["viewed_indices"].items():
        if lid not in valid_ids or not isinstance(indices, list):
            continue
        viewed[lid] = [int(i) for i in indices if isinstance(i, int)]
    state["viewed_indices"] = viewed

    current = state.get("current_listing_id")
    if current not in valid_ids:
        state["current_listing_id"] = None

    if state.get("mode") not in {"labeling", "edit"}:
        state["mode"] = "labeling"

    state["warnings"] = warnings
    return state, warnings


def load_state(state_path: Path, project_id: str) -> tuple[dict[str, Any], list[str], str | None]:
    if not state_path.exists():
        return default_state(project_id), [], None

    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        backup_path = state_path.with_suffix(".broken.json")
        shutil.copy2(state_path, backup_path)
        return default_state(project_id), [], f"Файл состояния поврежден и сохранен в {backup_path.name}: {exc}"

    try:
        state, warnings = validate_state(raw)
        state["project_id"] = project_id
        return state, warnings, None
    except StateValidationError as exc:
        backup_path = state_path.with_suffix(".invalid.json")
        shutil.copy2(state_path, backup_path)
        return default_state(project_id), [], f"Файл состояния невалиден и сохранен в {backup_path.name}: {exc}"


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    state = dict(state)
    state["state_version"] = STATE_VERSION
    state.pop("warnings", None)
    atomic_write_text(state_path, json.dumps(state, ensure_ascii=False, indent=2))


def save_results(results_csv: Path, labels: dict[str, int], listings: list[dict[str, Any]]) -> None:
    lookup = {item["listing_id"]: item for item in listings}
    rows = []
    for listing_id in sorted(labels):
        if listing_id not in lookup:
            continue
        rows.append(
            {
                "listing_id": listing_id,
                "shown_photo_indices": json.dumps(lookup[listing_id]["shown_indices"], ensure_ascii=False),
                "label": labels[listing_id],
            }
        )
    atomic_write_csv(results_csv, rows, ["listing_id", "shown_photo_indices", "label"])


def save_metadata(metadata_path: Path, metadata: ProjectMetadata) -> None:
    atomic_write_text(metadata_path, json.dumps(asdict(metadata), ensure_ascii=False, indent=2))


def read_metadata(metadata_path: Path) -> ProjectMetadata | None:
    if not metadata_path.exists():
        return None
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        return ProjectMetadata(**raw)
    except Exception:
        return None


def list_projects(projects_dir: Path) -> list[ProjectMetadata]:
    items: list[ProjectMetadata] = []
    for child in sorted([p for p in projects_dir.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True):
        meta = read_metadata(child / "metadata.json")
        if meta:
            items.append(meta)
    return items


def make_project_id(prefix: str = "project") -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{now}"
