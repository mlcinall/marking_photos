from __future__ import annotations

from collections import Counter
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from storage import load_session, save_results_csv, save_session
from utils import build_listing_index, ensure_directories, extract_uploaded_zip

BASE_DIR = Path(__file__).resolve().parent
DIRS = ensure_directories(BASE_DIR)
SESSION_PATH = DIRS["data"] / "session_state.json"
RESULTS_CSV_PATH = DIRS["data"] / "results.csv"
LOG_PATH = DIRS["logs"] / "skipped.log"


st.set_page_config(page_title="Разметка объявлений", page_icon="🏡", layout="wide")

st.markdown(
    """
    <style>
    .header-card {
        border-radius: 14px;
        padding: 1rem 1.25rem;
        background: linear-gradient(135deg, rgba(57,100,255,0.14), rgba(80,196,255,0.10));
        border: 1px solid rgba(80,196,255,0.3);
        margin-bottom: 1rem;
    }
    .photo-meta {
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: .2rem;
    }
    .muted { color: #8b96a8; font-size: .9rem; }
    .stat-card {
        border: 1px solid rgba(110, 118, 129, 0.2);
        border-radius: 12px;
        padding: .8rem;
        background: rgba(255, 255, 255, 0.02);
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def persist(state: dict) -> None:
    save_session(SESSION_PATH, state)
    save_results_csv(RESULTS_CSV_PATH, state["labels"], state["listings"])


def next_unlabeled_id(state: dict) -> str | None:
    for listing in state["listings"]:
        if listing["listing_id"] not in state["labels"]:
            return listing["listing_id"]
    return None


def listing_by_id(state: dict, listing_id: str) -> dict:
    return next(item for item in state["listings"] if item["listing_id"] == listing_id)


def set_current_listing(state: dict, listing_id: str | None) -> None:
    state["current_listing_id"] = listing_id
    persist(state)


def apply_label(state: dict, listing_id: str, new_label: int) -> None:
    previous_label = state["labels"].get(listing_id)
    state["labels"][listing_id] = new_label
    state["actions"].append(
        {
            "listing_id": listing_id,
            "previous_label": previous_label,
            "new_label": new_label,
        }
    )

    state["current_listing_id"] = next_unlabeled_id(state)
    persist(state)


def undo_last_action(state: dict) -> bool:
    if not state["actions"]:
        return False

    action = state["actions"].pop()
    listing_id = action["listing_id"]
    previous_label = action["previous_label"]

    if previous_label is None:
        state["labels"].pop(listing_id, None)
    else:
        state["labels"][listing_id] = previous_label

    state["current_listing_id"] = listing_id
    listing = listing_by_id(state, listing_id)
    state["photo_cursor"][listing_id] = max(0, len(listing["shown_files"]) - 1)
    persist(state)
    return True


def init_state() -> dict:
    if "session_data" not in st.session_state:
        st.session_state.session_data = load_session(SESSION_PATH)
    return st.session_state.session_data


def inject_hotkeys() -> None:
    components.html(
        """
        <script>
        const bindings = {
            ArrowLeft: '◀ Назад (A/←)',
            ArrowRight: 'Вперед ▶ (D/→)',
            a: '◀ Назад (A/←)',
            d: 'Вперед ▶ (D/→)',
            0: 'Класс 0 (не нравится)',
            1: 'Класс 1 (нравится)',
            2: 'Класс 2 (не определено)',
            u: '↩ Undo (U/Backspace)',
            Backspace: '↩ Undo (U/Backspace)'
        };

        window.addEventListener('keydown', (event) => {
            const key = event.key;
            const targetText = bindings[key];
            if (!targetText) return;

            const buttons = window.parent.document.querySelectorAll('button');
            for (const btn of buttons) {
                const text = btn.innerText.trim();
                if (text === targetText) {
                    btn.click();
                    event.preventDefault();
                    return;
                }
            }
        });
        </script>
        """,
        height=0,
    )


def load_uploaded_dataset(state: dict) -> None:
    uploaded_zip = st.file_uploader("Загрузите ZIP-архив с объявлениями", type=["zip"])
    if not uploaded_zip:
        return

    if st.button("Импортировать архив", use_container_width=True):
        dataset_root = extract_uploaded_zip(uploaded_zip, DIRS["uploads"], DIRS["extracted"])
        listing_objects = build_listing_index(dataset_root, LOG_PATH)

        state["dataset_root"] = str(dataset_root.resolve())
        state["listings"] = [
            {
                "listing_id": item.listing_id,
                "directory": item.directory,
                "shown_indices": item.shown_indices,
                "shown_files": item.shown_files,
            }
            for item in listing_objects
        ]
        state["labels"] = {}
        state["actions"] = []
        state["photo_cursor"] = {}
        state["current_listing_id"] = next_unlabeled_id(state)
        persist(state)
        st.success(f"Импорт завершен: {len(state['listings'])} объявлений доступно для разметки.")


def ensure_current_listing(state: dict) -> None:
    if not state["listings"]:
        state["current_listing_id"] = None
        return

    if state["current_listing_id"] is None:
        state["current_listing_id"] = next_unlabeled_id(state) or state["listings"][0]["listing_id"]


def render_sidebar(state: dict) -> None:
    total = len(state["listings"])
    labeled = len(state["labels"])
    remaining = max(total - labeled, 0)
    completion = (labeled / total) if total else 0

    st.sidebar.header("Статус проекта")
    st.sidebar.progress(completion)
    st.sidebar.caption(f"Размечено: {labeled} / {total}")
    st.sidebar.caption(f"Осталось: {remaining}")
    st.sidebar.caption(f"Готово: {completion * 100:.1f}%")

    counts = Counter(state["labels"].values())
    st.sidebar.markdown("### Статистика классов")
    st.sidebar.markdown(
        f"- Класс **0**: `{counts.get(0, 0)}`\n"
        f"- Класс **1**: `{counts.get(1, 0)}`\n"
        f"- Класс **2**: `{counts.get(2, 0)}`"
    )

    if st.sidebar.button("↩ Undo (U/Backspace)", use_container_width=True):
        if undo_last_action(state):
            st.sidebar.success("Последнее действие отменено")
            st.rerun()
        st.sidebar.warning("История пуста")

    labeled_ids = sorted(state["labels"].keys())
    st.sidebar.markdown("### Изменить уже размеченное")
    selected = st.sidebar.selectbox(
        "Открыть объявление",
        options=["—"] + labeled_ids,
        help="Выберите объявление, чтобы пересмотреть фото и поменять класс",
    )
    if selected != "—" and st.sidebar.button("Открыть выбранное", use_container_width=True):
        set_current_listing(state, selected)
        st.rerun()


def render_main(state: dict) -> None:
    if not state["listings"]:
        st.info("Загрузите ZIP-архив, чтобы начать разметку.")
        return

    ensure_current_listing(state)
    current_id = state["current_listing_id"]
    if current_id is None:
        st.success("Все объявления размечены. Можно открыть любое в правой панели для редактирования.")
        return

    listing = listing_by_id(state, current_id)
    photo_total = len(listing["shown_files"])
    cursor = state["photo_cursor"].get(current_id, 0)
    cursor = max(0, min(cursor, photo_total - 1))
    state["photo_cursor"][current_id] = cursor

    st.markdown(
        f"""
        <div class="header-card">
            <div class="photo-meta">Объявление: <code>{current_id}</code></div>
            <div>Фото {cursor + 1} из {photo_total}</div>
            <div class="muted">Показываются только изображения с индексами: {listing['shown_indices']}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.image(listing["shown_files"][cursor], use_container_width=True)

    nav_col1, nav_col2, _ = st.columns([1, 1, 3])
    if nav_col1.button("◀ Назад (A/←)", use_container_width=True, disabled=cursor == 0):
        state["photo_cursor"][current_id] = max(0, cursor - 1)
        persist(state)
        st.rerun()

    if nav_col2.button("Вперед ▶ (D/→)", use_container_width=True, disabled=cursor >= photo_total - 1):
        state["photo_cursor"][current_id] = min(photo_total - 1, cursor + 1)
        persist(state)
        st.rerun()

    is_last_photo = cursor >= photo_total - 1
    st.markdown("### Классификация")
    st.caption("Кнопки становятся активными после просмотра последнего фото.")
    class_cols = st.columns(3)

    if class_cols[0].button("Класс 0 (не нравится)", use_container_width=True, disabled=not is_last_photo):
        apply_label(state, current_id, 0)
        st.rerun()

    if class_cols[1].button("Класс 1 (нравится)", use_container_width=True, disabled=not is_last_photo):
        apply_label(state, current_id, 1)
        st.rerun()

    if class_cols[2].button("Класс 2 (не определено)", use_container_width=True, disabled=not is_last_photo):
        apply_label(state, current_id, 2)
        st.rerun()


def main() -> None:
    st.title("🏡 Разметка фотографий объявлений недвижимости")
    st.caption("Горячие клавиши: ←/→ или A/D, 0/1/2 для класса, U или Backspace для Undo")

    state = init_state()
    inject_hotkeys()

    with st.expander("Импорт данных", expanded=not bool(state["listings"])):
        load_uploaded_dataset(state)

    render_sidebar(state)
    render_main(state)


if __name__ == "__main__":
    main()
