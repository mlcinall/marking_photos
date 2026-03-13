from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

from PIL import Image, UnidentifiedImageError

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class ListingData:
    listing_id: str
    directory: str
    shown_indices: List[int]
    shown_files: List[str]


def ensure_directories(base_dir: Path) -> dict[str, Path]:
    data_dir = base_dir / "data"
    uploads_dir = data_dir / "uploads"
    extracted_dir = data_dir / "extracted"
    logs_dir = data_dir / "logs"

    for path in (data_dir, uploads_dir, extracted_dir, logs_dir):
        path.mkdir(parents=True, exist_ok=True)

    return {
        "data": data_dir,
        "uploads": uploads_dir,
        "extracted": extracted_dir,
        "logs": logs_dir,
    }


def extract_uploaded_zip(uploaded_file, uploads_dir: Path, extracted_dir: Path) -> Path:
    zip_path = uploads_dir / uploaded_file.name
    zip_path.write_bytes(uploaded_file.getvalue())

    for child in extracted_dir.iterdir():
        if child.is_dir():
            for nested in child.glob("**/*"):
                if nested.is_file():
                    nested.unlink(missing_ok=True)
            for nested_dir in sorted(child.glob("**/*"), reverse=True):
                if nested_dir.is_dir():
                    nested_dir.rmdir()
            child.rmdir()
        else:
            child.unlink(missing_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extracted_dir)

    roots = [p for p in extracted_dir.iterdir() if p.is_dir()]
    if len(roots) == 1:
        nested_listing_dirs = [p for p in roots[0].iterdir() if p.is_dir()]
        if nested_listing_dirs:
            return roots[0]
    return extracted_dir


def _is_image_readable(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        return False


def build_listing_index(dataset_root: Path, log_path: Path) -> list[ListingData]:
    listings: list[ListingData] = []
    log_messages: list[str] = []

    for folder in sorted([p for p in dataset_root.iterdir() if p.is_dir()], key=lambda p: p.name):
        image_files = sorted(
            [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS],
            key=lambda p: p.name,
        )

        shown_indices: list[int] = []
        shown_files: list[str] = []

        for idx, image_path in enumerate(image_files):
            if idx % 2 != 0:
                continue
            if _is_image_readable(image_path):
                shown_indices.append(idx)
                shown_files.append(str(image_path.resolve()))
            else:
                log_messages.append(
                    f"[{folder.name}] corrupted image skipped: {image_path.name} (sorted index={idx})"
                )

        if not shown_files:
            log_messages.append(f"[{folder.name}] skipped: no readable images on even indices")
            continue

        listings.append(
            ListingData(
                listing_id=folder.name,
                directory=str(folder.resolve()),
                shown_indices=shown_indices,
                shown_files=shown_files,
            )
        )

    if log_messages:
        with log_path.open("a", encoding="utf-8") as fp:
            fp.write("\n".join(log_messages) + "\n")

    return listings


