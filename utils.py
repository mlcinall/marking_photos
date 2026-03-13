from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class ListingData:
    listing_id: str
    directory: str
    shown_indices: list[int]
    shown_files: list[str]


@dataclass
class ImportSummary:
    source_zip_name: str
    root_mode: str
    total_listing_folders: int
    valid_listings: int
    skipped_listings: int
    skipped_reasons: dict[str, int]


class ImportErrorUserFriendly(Exception):
    pass


def reset_directory(path: Path) -> None:
    """Safely recreate directory regardless of nested content."""
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.infolist():
        member_path = destination / member.filename
        resolved_member = member_path.resolve()
        if not str(resolved_member).startswith(str(destination)):
            raise ImportErrorUserFriendly(f"ZIP содержит небезопасный путь: {member.filename}")
        if member.is_dir():
            resolved_member.mkdir(parents=True, exist_ok=True)
            continue

        resolved_member.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as src, resolved_member.open("wb") as dst:
            shutil.copyfileobj(src, dst)


def extract_uploaded_zip(uploaded_file, project_extracted_dir: Path) -> Path:
    reset_directory(project_extracted_dir)

    try:
        with zipfile.ZipFile(uploaded_file, "r") as archive:
            _safe_extract(archive, project_extracted_dir)
    except zipfile.BadZipFile as exc:
        raise ImportErrorUserFriendly("Файл не является корректным ZIP-архивом") from exc

    root_entries = list(project_extracted_dir.iterdir())
    dir_entries = [p for p in root_entries if p.is_dir()]

    # archive/<listing_id>/* or archive/<root>/<listing_id>/*
    if len(dir_entries) == 1:
        candidate_root = dir_entries[0]
        child_dirs = [p for p in candidate_root.iterdir() if p.is_dir()]
        if child_dirs:
            return candidate_root

    return project_extracted_dir


def _is_image_readable(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def build_listing_index(dataset_root: Path) -> tuple[list[ListingData], ImportSummary, list[str]]:
    listings: list[ListingData] = []
    logs: list[str] = []

    listing_folders = sorted([p for p in dataset_root.iterdir() if p.is_dir()], key=lambda p: p.name)
    skipped_reasons: dict[str, int] = {
        "empty_folder": 0,
        "no_supported_images": 0,
        "no_even_readable_images": 0,
    }

    for folder in listing_folders:
        all_files = sorted([f for f in folder.iterdir() if f.is_file()], key=lambda p: p.name)
        if not all_files:
            skipped_reasons["empty_folder"] += 1
            logs.append(f"[{folder.name}] skipped: empty listing folder")
            continue

        image_files = [f for f in all_files if f.suffix.lower() in SUPPORTED_EXTENSIONS]
        if not image_files:
            skipped_reasons["no_supported_images"] += 1
            logs.append(f"[{folder.name}] skipped: no supported images")
            continue

        shown_indices: list[int] = []
        shown_files: list[str] = []
        for idx, image_path in enumerate(image_files):
            if idx % 2 != 0:
                continue
            if _is_image_readable(image_path):
                shown_indices.append(idx)
                shown_files.append(str(image_path.resolve()))
            else:
                logs.append(f"[{folder.name}] corrupted image skipped: {image_path.name} (index={idx})")

        if not shown_files:
            skipped_reasons["no_even_readable_images"] += 1
            logs.append(f"[{folder.name}] skipped: no readable images for even indices")
            continue

        listings.append(
            ListingData(
                listing_id=folder.name,
                directory=str(folder.resolve()),
                shown_indices=shown_indices,
                shown_files=shown_files,
            )
        )

    summary = ImportSummary(
        source_zip_name="",
        root_mode="single_nested_root" if dataset_root.parent.name == "extracted" else "flat_or_mixed_root",
        total_listing_folders=len(listing_folders),
        valid_listings=len(listings),
        skipped_listings=len(listing_folders) - len(listings),
        skipped_reasons=skipped_reasons,
    )
    return listings, summary, logs


def append_logs(log_path: Path, messages: list[str]) -> None:
    if not messages:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write("\n".join(messages) + "\n")


def listing_table_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for listing in state.get("listings", []):
        lid = listing["listing_id"]
        label = state.get("labels", {}).get(lid)
        rows.append(
            {
                "listing_id": lid,
                "photos_shown": len(listing["shown_files"]),
                "shown_indices": listing["shown_indices"],
                "label": label if label is not None else "—",
            }
        )
    return rows
