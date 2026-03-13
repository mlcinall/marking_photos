from __future__ import annotations

from collections import Counter
from pathlib import Path

import streamlit as st

from keyboard_shortcuts import listen_hotkeys
from project_store import (
    ProjectMetadata,
    ensure_data_layout,
    list_projects,
    load_state,
    make_project_id,
    project_paths,
    save_metadata,
    save_results,
    save_state,
)
from utils import (
    ImportErrorUserFriendly,
    append_logs,
    build_listing_index,
    extract_uploaded_zip,
    listing_table_rows,
)

BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = ensure_data_layout(BASE_DIR)


st.set_page_config(page_title="Разметка недвижимости", page_icon="🏡", layout="wide")

st.markdown(
    """
    <style>
    .card {border:1px solid rgba(120,120,120,.25); border-radius:14px; padding:14px; margin-bottom:10px;}
    .muted {color:#8b96a8;}
    .tag {display:inline-block; padding:3px 8px; border-radius:999px; border:1px solid rgba(120,120,120,.35); margin-right:6px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def init_app_state() -> None:
    if "active_project_id" not in st.session_state:
        st.session_state.active_project_id = ""
    if "state" not in st.session_state:
        st.session_state.state = None
    if "paths" not in st.session_state:
        st.session_state.paths = None
    if "project_warning" not in st.session_state:
        st.session_state.project_warning = ""


def persist() -> None:
    state = st.session_state.state
    paths = st.session_state.paths
    save_state(paths.state_file, state)
    save_results(paths.results_csv, state["labels"], state["listings"])


def next_unlabeled(state: dict) -> str | None:
    for item in state["listings"]:
        if item["listing_id"] not in state["labels"]:
            return item["listing_id"]
    return None


def get_listing(state: dict, listing_id: str) -> dict:
    return next(x for x in state["listings"] if x["listing_id"] == listing_id)


def open_project(project_id: str) -> None:
    paths = project_paths(PROJECTS_DIR / project_id)
    state, warnings, hard_warning = load_state(paths.state_file, project_id)
    st.session_state.active_project_id = project_id
    st.session_state.state = state
    st.session_state.paths = paths
    st.session_state.project_warning = hard_warning or ("; ".join(warnings) if warnings else "")


def create_project_from_zip(uploaded_zip, project_name: str) -> None:
    project_id = make_project_id()
    pdir = PROJECTS_DIR / project_id
    paths = project_paths(pdir)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.logs.mkdir(parents=True, exist_ok=True)

    dataset_root = extract_uploaded_zip(uploaded_zip, paths.extracted)
    preview_root = paths.root / "previews"
    listings, summary, logs = build_listing_index(dataset_root, preview_root)

    state = {
        "state_version": 2,
        "project_id": project_id,
        "dataset_root": str(dataset_root.resolve()),
        "listings": [
            {
                "listing_id": x.listing_id,
                "directory": x.directory,
                "shown_indices": x.shown_indices,
                "shown_files": x.shown_files,
                "shown_previews": x.shown_previews,
            }
            for x in listings
        ],
        "labels": {},
        "actions": [],
        "photo_cursor": {},
        "viewed_indices": {},
        "current_listing_id": listings[0].listing_id if listings else None,
        "mode": "labeling",
    }

    append_logs(paths.logs / "skipped.log", logs)

    meta = ProjectMetadata(
        project_id=project_id,
        project_name=project_name or project_id,
        source_zip_name=uploaded_zip.name,
        imported_at=__import__("datetime").datetime.now().isoformat(timespec="seconds"),
        root_mode=summary.root_mode,
        total_listing_folders=summary.total_listing_folders,
        valid_listings=summary.valid_listings,
        skipped_listings=summary.skipped_listings,
    )

    save_metadata(paths.metadata_file, meta)
    st.session_state.active_project_id = project_id
    st.session_state.state = state
    st.session_state.paths = paths
    st.session_state.project_warning = ""
    persist()

    st.success(
        "Импорт завершен: "
        f"папок={summary.total_listing_folders}, валидных={summary.valid_listings}, пропущено={summary.skipped_listings}"
    )
    with st.expander("Почему объявления были пропущены"):
        st.json(summary.skipped_reasons)


def set_label(listing_id: str, label: int) -> None:
    state = st.session_state.state
    prev = state["labels"].get(listing_id)
    state["labels"][listing_id] = label
    state["actions"].append({"listing_id": listing_id, "previous_label": prev, "new_label": label})
    state["mode"] = "labeling"
    state["current_listing_id"] = next_unlabeled(state)
    persist()


def do_undo() -> None:
    state = st.session_state.state
    if not state["actions"]:
        st.warning("Undo недоступен: история пуста.")
        return

    action = state["actions"].pop()
    lid = action["listing_id"]
    if action["previous_label"] is None:
        state["labels"].pop(lid, None)
    else:
        state["labels"][lid] = action["previous_label"]

    state["current_listing_id"] = lid
    state["mode"] = "edit"
    listing = get_listing(state, lid)
    state["photo_cursor"][lid] = len(listing["shown_files"]) - 1
    state["viewed_indices"][lid] = list(range(len(listing["shown_files"])))
    persist()


def ensure_current_listing() -> None:
    state = st.session_state.state
    if not state["listings"]:
        state["current_listing_id"] = None
        return
    if state["current_listing_id"] is None:
        state["current_listing_id"] = next_unlabeled(state)


def handle_hotkeys() -> None:
    if not st.session_state.state:
        return

    action = listen_hotkeys(enabled=True, key="global_hotkeys")
    if not action:
        return

    state = st.session_state.state
    current_id = state.get("current_listing_id")

    if action == "undo":
        do_undo()
        st.rerun()
        return

    if not current_id:
        return

    listing = get_listing(state, current_id)
    cursor = int(state["photo_cursor"].get(current_id, 0))
    total = len(listing["shown_files"])

    if action == "prev":
        state["photo_cursor"][current_id] = max(0, cursor - 1)
        st.rerun()
    elif action == "next":
        state["photo_cursor"][current_id] = min(total - 1, cursor + 1)
        st.rerun()
    elif action in {"label0", "label1", "label2"}:
        viewed = set(state["viewed_indices"].get(current_id, []))
        if len(viewed) == total:
            set_label(current_id, int(action[-1]))
            st.rerun()


def render_project_manager() -> None:
    st.sidebar.header("Проекты")
    projects = list_projects(PROJECTS_DIR)

    selected = st.sidebar.selectbox("Открыть проект", options=["—"] + [p.project_id for p in projects])
    if selected != "—" and st.sidebar.button("Открыть", use_container_width=True):
        open_project(selected)
        st.rerun()

    with st.sidebar.expander("Создать новый проект из ZIP", expanded=not bool(projects)):
        project_name = st.text_input("Название проекта", value="")
        uploaded_zip = st.file_uploader("ZIP-архив", type=["zip"])
        if st.button("Импортировать в новый проект", use_container_width=True):
            if not uploaded_zip:
                st.error("Сначала выберите ZIP-файл.")
                return
            try:
                create_project_from_zip(uploaded_zip, project_name.strip())
                st.rerun()
            except ImportErrorUserFriendly as exc:
                st.error(str(exc))


def render_sidebar_status() -> None:
    if not st.session_state.state:
        return

    state = st.session_state.state
    total = len(state["listings"])
    labeled = len(state["labels"])
    percent = (labeled / total) if total else 0
    counts = Counter(state["labels"].values())

    st.sidebar.markdown("---")
    st.sidebar.subheader("Статус")
    st.sidebar.progress(percent)
    st.sidebar.caption(f"Размечено: {labeled}/{total}")
    st.sidebar.caption(f"Осталось: {max(total-labeled, 0)}")
    st.sidebar.caption(f"Выполнено: {percent*100:.1f}%")
    st.sidebar.markdown(f"Класс 0: **{counts.get(0,0)}**  ")
    st.sidebar.markdown(f"Класс 1: **{counts.get(1,0)}**  ")
    st.sidebar.markdown(f"Класс 2: **{counts.get(2,0)}**")

    if st.sidebar.button("Undo (U/Backspace)", use_container_width=True):
        do_undo()
        st.rerun()

    st.sidebar.download_button(
        "Скачать results.csv",
        data=st.session_state.paths.results_csv.read_bytes() if st.session_state.paths.results_csv.exists() else b"",
        file_name=f"{st.session_state.active_project_id}_results.csv",
        mime="text/csv",
        use_container_width=True,
    )


def render_main() -> None:
    if not st.session_state.state:
        st.info("Создайте новый проект или откройте существующий в боковой панели.")
        return

    state = st.session_state.state
    paths = st.session_state.paths

    if st.session_state.project_warning:
        st.warning(st.session_state.project_warning)

    st.markdown(f"### Текущий проект: `{st.session_state.active_project_id}`")
    if paths.metadata_file.exists():
        st.caption(f"Метаданные: {paths.metadata_file.name} | Подсказка: используйте клавиши ← → A D 0 1 2 U")

    ensure_current_listing()
    current_id = state["current_listing_id"]

    with st.expander("Размеченные объявления и редактирование", expanded=False):
        rows = listing_table_rows(state)
        st.dataframe(rows, use_container_width=True, hide_index=True, height=260)
        labeled_ids = sorted(state["labels"].keys())
        col_edit1, col_edit2 = st.columns([3, 1])
        selected = col_edit1.selectbox("Открыть объявление для редактирования", options=["—"] + labeled_ids)
        if selected != "—" and col_edit2.button("Редактировать", use_container_width=True):
            state["current_listing_id"] = selected
            state["mode"] = "edit"
            listing = get_listing(state, selected)
            state["viewed_indices"][selected] = list(range(len(listing["shown_files"])))
            persist()
            st.rerun()

    if not current_id:
        st.success("Все объявления размечены. Можно редактировать ранее сохранённые метки.")
        return

    listing = get_listing(state, current_id)
    total_photos = len(listing["shown_files"])
    cursor = int(state["photo_cursor"].get(current_id, 0))
    cursor = max(0, min(cursor, total_photos - 1))
    state["photo_cursor"][current_id] = cursor

    viewed = set(state["viewed_indices"].get(current_id, []))
    viewed.add(cursor)
    state["viewed_indices"][current_id] = sorted(viewed)

    is_fully_viewed = len(viewed) == total_photos
    current_label = state["labels"].get(current_id)

    status_tag = "РАЗМЕЧЕНО" if current_label is not None else "НЕ РАЗМЕЧЕНО"
    mode_tag = "Режим редактирования" if state.get("mode") == "edit" else "Первичная разметка"

    st.markdown(
        f"""
        <div class='card'>
          <div><span class='tag'>{mode_tag}</span><span class='tag'>{status_tag}</span></div>
          <h4>Объявление: <code>{current_id}</code></h4>
          <div class='muted'>Фото {cursor+1} из {total_photos} | Просмотрено: {len(viewed)}/{total_photos}</div>
          <div class='muted'>Показываемые индексы: {listing['shown_indices']}</div>
          <div class='muted'>Текущая метка: {current_label if current_label is not None else 'не задана'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    preview_path = listing.get("shown_previews", listing["shown_files"])[cursor]
    st.image(preview_path, use_container_width=True)

    col1, col2, _ = st.columns([1, 1, 4])
    if col1.button("◀ Назад", disabled=cursor == 0, use_container_width=True):
        state["photo_cursor"][current_id] = cursor - 1
        st.rerun()
    if col2.button("Вперёд ▶", disabled=cursor >= total_photos - 1, use_container_width=True):
        state["photo_cursor"][current_id] = cursor + 1
        st.rerun()

    st.caption("Классификация доступна только после просмотра всех показываемых фото этого объявления.")
    c0, c1, c2 = st.columns(3)
    if c0.button("Класс 0", disabled=not is_fully_viewed, use_container_width=True):
        set_label(current_id, 0)
        st.rerun()
    if c1.button("Класс 1", disabled=not is_fully_viewed, use_container_width=True):
        set_label(current_id, 1)
        st.rerun()
    if c2.button("Класс 2", disabled=not is_fully_viewed, use_container_width=True):
        set_label(current_id, 2)
        st.rerun()


def main() -> None:
    st.title("🏡 Разметка фотографий объявлений недвижимости")
    st.caption("Быстрый режим: ←/→ или A/D для листания, 0/1/2 для класса, U/Backspace для Undo")

    init_app_state()
    render_project_manager()

    if st.session_state.active_project_id and st.session_state.state is None:
        open_project(st.session_state.active_project_id)

    handle_hotkeys()
    render_sidebar_status()
    render_main()


if __name__ == "__main__":
    main()
