"""Compatibility module.

The project previously used `storage.py` directly from `app.py`.
Now durable project-aware persistence lives in `project_store.py`.
This file is intentionally kept to avoid breaking imports in external scripts.
"""

from project_store import (  # noqa: F401
    ProjectMetadata,
    StateValidationError,
    atomic_write_csv,
    atomic_write_text,
    default_state,
    ensure_data_layout,
    list_projects,
    load_state,
    make_project_id,
    project_paths,
    save_metadata,
    save_results,
    save_state,
)
