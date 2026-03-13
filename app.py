from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

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
from utils import append_logs, build_listing_index, extract_uploaded_zip

BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = ensure_data_layout(BASE_DIR)


class ImageLabel(QLabel):
    def __init__(self) -> None:
        super().__init__("Загрузите проект")
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border:1px solid #999; background:#151515; color:#ddd;")
        self._pixmap: QPixmap | None = None

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._render()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._render()

    def _render(self) -> None:
        if not self._pixmap:
            return
        # fit-to-window UX: image is contained in 75% of available height area
        scaled = self._pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(scaled)


class LabelingApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Real Estate Photo Labeler")
        self.resize(1500, 950)

        self.active_project_id: str | None = None
        self.paths = None
        self.state: dict | None = None

        self._build_ui()
        self._bind_shortcuts()
        self.refresh_project_list()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter)

        # Left panel
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        project_box = QGroupBox("Проекты")
        project_layout = QVBoxLayout(project_box)
        self.project_list = QListWidget()
        self.project_list.itemDoubleClicked.connect(lambda _: self.open_selected_project())
        project_layout.addWidget(self.project_list)

        row = QHBoxLayout()
        self.btn_open_project = QPushButton("Открыть")
        self.btn_open_project.clicked.connect(self.open_selected_project)
        self.btn_refresh_projects = QPushButton("Обновить")
        self.btn_refresh_projects.clicked.connect(self.refresh_project_list)
        row.addWidget(self.btn_open_project)
        row.addWidget(self.btn_refresh_projects)
        project_layout.addLayout(row)

        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("Название нового проекта (опционально)")
        self.btn_import_zip = QPushButton("Импортировать ZIP в новый проект")
        self.btn_import_zip.clicked.connect(self.create_project_from_zip_dialog)
        project_layout.addWidget(self.project_name)
        project_layout.addWidget(self.btn_import_zip)

        left_layout.addWidget(project_box)

        stats_box = QGroupBox("Статус")
        stats_layout = QVBoxLayout(stats_box)
        self.lbl_project = QLabel("Проект: —")
        self.lbl_progress = QLabel("Прогресс: 0/0 (0.0%)")
        self.lbl_remaining = QLabel("Осталось: 0")
        self.lbl_counts = QLabel("Классы: 0=0, 1=0, 2=0")
        stats_layout.addWidget(self.lbl_project)
        stats_layout.addWidget(self.lbl_progress)
        stats_layout.addWidget(self.lbl_remaining)
        stats_layout.addWidget(self.lbl_counts)
        left_layout.addWidget(stats_box)

        self.btn_undo = QPushButton("Undo (U/Backspace)")
        self.btn_undo.clicked.connect(self.undo)
        left_layout.addWidget(self.btn_undo)

        logs_box = QGroupBox("Сообщения")
        logs_layout = QVBoxLayout(logs_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(220)
        logs_layout.addWidget(self.log_view)
        left_layout.addWidget(logs_box)

        splitter.addWidget(left_panel)

        # Center panel
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)

        meta_box = QGroupBox("Текущее объявление")
        meta_layout = QGridLayout(meta_box)
        self.lbl_listing_id = QLabel("listing_id: —")
        self.lbl_listing_mode = QLabel("режим: —")
        self.lbl_listing_status = QLabel("статус: —")
        self.lbl_photo_progress = QLabel("Фото: —")
        self.lbl_viewed = QLabel("Просмотрено: —")
        self.lbl_label = QLabel("Метка: —")
        meta_layout.addWidget(self.lbl_listing_id, 0, 0)
        meta_layout.addWidget(self.lbl_listing_mode, 0, 1)
        meta_layout.addWidget(self.lbl_listing_status, 1, 0)
        meta_layout.addWidget(self.lbl_photo_progress, 1, 1)
        meta_layout.addWidget(self.lbl_viewed, 2, 0)
        meta_layout.addWidget(self.lbl_label, 2, 1)
        center_layout.addWidget(meta_box)

        self.image_view = ImageLabel()
        self.image_view.setMinimumHeight(560)
        center_layout.addWidget(self.image_view, stretch=1)

        nav = QHBoxLayout()
        self.btn_prev = QPushButton("◀ Назад (A/←)")
        self.btn_next = QPushButton("Вперёд ▶ (D/→)")
        self.btn_prev.clicked.connect(self.prev_photo)
        self.btn_next.clicked.connect(self.next_photo)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        center_layout.addLayout(nav)

        classes = QHBoxLayout()
        self.btn_c0 = QPushButton("Класс 0")
        self.btn_c1 = QPushButton("Класс 1")
        self.btn_c2 = QPushButton("Класс 2")
        self.btn_c0.clicked.connect(lambda: self.set_label(0))
        self.btn_c1.clicked.connect(lambda: self.set_label(1))
        self.btn_c2.clicked.connect(lambda: self.set_label(2))
        classes.addWidget(self.btn_c0)
        classes.addWidget(self.btn_c1)
        classes.addWidget(self.btn_c2)
        center_layout.addLayout(classes)

        splitter.addWidget(center_panel)

        # Right panel (heavy table isolated from hot path updates)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_box = QGroupBox("Размеченные объявления / редактирование")
        rb_layout = QVBoxLayout(right_box)
        self.list_labeled = QListWidget()
        self.list_labeled.itemDoubleClicked.connect(lambda _: self.open_for_edit())
        self.btn_open_edit = QPushButton("Открыть для редактирования")
        self.btn_open_edit.clicked.connect(self.open_for_edit)
        self.table_overview = QTableWidget(0, 3)
        self.table_overview.setHorizontalHeaderLabels(["listing_id", "shown_indices", "label"])
        self.table_overview.setMinimumHeight(320)
        rb_layout.addWidget(self.list_labeled)
        rb_layout.addWidget(self.btn_open_edit)
        rb_layout.addWidget(self.table_overview)
        right_layout.addWidget(right_box)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)

    def _bind_shortcuts(self) -> None:
        for key in (Qt.Key_Left, Qt.Key_A):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(self.prev_photo)
        for key in (Qt.Key_Right, Qt.Key_D):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(self.next_photo)
        for key, value in ((Qt.Key_0, 0), (Qt.Key_1, 1), (Qt.Key_2, 2)):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda v=value: self.set_label(v))
        for key in (Qt.Key_U, Qt.Key_Backspace):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(self.undo)

    def log(self, message: str) -> None:
        self.log_view.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def refresh_project_list(self) -> None:
        self.project_list.clear()
        for meta in list_projects(PROJECTS_DIR):
            text = f"{meta.project_id} | {meta.project_name} | valid={meta.valid_listings}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, meta.project_id)
            self.project_list.addItem(item)

    def create_project_from_zip_dialog(self) -> None:
        zip_path, _ = QFileDialog.getOpenFileName(self, "Выберите ZIP", str(BASE_DIR), "ZIP (*.zip)")
        if not zip_path:
            return

        project_id = make_project_id()
        pdir = PROJECTS_DIR / project_id
        paths = project_paths(pdir)
        paths.root.mkdir(parents=True, exist_ok=True)
        paths.logs.mkdir(parents=True, exist_ok=True)

        try:
            with open(zip_path, "rb") as fp:
                dataset_root = extract_uploaded_zip(fp, paths.extracted)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка импорта", str(exc))
            return

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

        meta = ProjectMetadata(
            project_id=project_id,
            project_name=self.project_name.text().strip() or project_id,
            source_zip_name=Path(zip_path).name,
            imported_at=datetime.now().isoformat(timespec="seconds"),
            root_mode=summary.root_mode,
            total_listing_folders=summary.total_listing_folders,
            valid_listings=summary.valid_listings,
            skipped_listings=summary.skipped_listings,
        )

        append_logs(paths.logs / "skipped.log", logs)
        save_metadata(paths.metadata_file, meta)
        save_state(paths.state_file, state)
        save_results(paths.results_csv, state["labels"], state["listings"])

        self.log(
            f"Импорт: папок={summary.total_listing_folders}, валидных={summary.valid_listings}, пропущено={summary.skipped_listings}"
        )
        self.refresh_project_list()
        self.open_project(project_id)

    def open_selected_project(self) -> None:
        item = self.project_list.currentItem()
        if not item:
            return
        project_id = item.data(Qt.UserRole)
        self.open_project(project_id)

    def open_project(self, project_id: str) -> None:
        self.paths = project_paths(PROJECTS_DIR / project_id)
        state, warnings, hard_warning = load_state(self.paths.state_file, project_id)
        self.active_project_id = project_id
        self.state = state
        if hard_warning:
            self.log(hard_warning)
        for w in warnings:
            self.log(w)
        self.update_ui(full_refresh=True)

    def current_listing(self) -> dict | None:
        if not self.state:
            return None
        current_id = self.state.get("current_listing_id")
        if not current_id:
            return None
        for listing in self.state["listings"]:
            if listing["listing_id"] == current_id:
                return listing
        return None

    def update_ui(self, full_refresh: bool = False) -> None:
        if not self.state:
            return

        total = len(self.state["listings"])
        labeled = len(self.state["labels"])
        remaining = max(total - labeled, 0)
        percent = (labeled / total * 100) if total else 0.0
        counts = Counter(self.state["labels"].values())

        self.lbl_project.setText(f"Проект: {self.active_project_id}")
        self.lbl_progress.setText(f"Прогресс: {labeled}/{total} ({percent:.1f}%)")
        self.lbl_remaining.setText(f"Осталось: {remaining}")
        self.lbl_counts.setText(
            f"Классы: 0={counts.get(0,0)}, 1={counts.get(1,0)}, 2={counts.get(2,0)}"
        )

        listing = self.current_listing()
        if not listing:
            self.image_view.setText("Все объявления размечены")
            return

        lid = listing["listing_id"]
        total_photos = len(listing["shown_files"])
        cursor = int(self.state["photo_cursor"].get(lid, 0))
        cursor = max(0, min(cursor, total_photos - 1))
        self.state["photo_cursor"][lid] = cursor

        viewed = set(self.state["viewed_indices"].get(lid, []))
        viewed.add(cursor)
        self.state["viewed_indices"][lid] = sorted(viewed)

        current_label = self.state["labels"].get(lid)
        is_fully_viewed = len(viewed) == total_photos

        self.lbl_listing_id.setText(f"listing_id: {lid}")
        self.lbl_listing_mode.setText(
            f"режим: {'редактирование' if self.state.get('mode') == 'edit' else 'первичная разметка'}"
        )
        self.lbl_listing_status.setText(
            f"статус: {'размечено' if current_label is not None else 'не размечено'}"
        )
        self.lbl_photo_progress.setText(f"Фото: {cursor + 1} / {total_photos}")
        self.lbl_viewed.setText(f"Просмотрено: {len(viewed)} / {total_photos}")
        self.lbl_label.setText(f"Метка: {current_label if current_label is not None else '—'}")

        self.btn_prev.setEnabled(cursor > 0)
        self.btn_next.setEnabled(cursor < total_photos - 1)
        self.btn_c0.setEnabled(is_fully_viewed)
        self.btn_c1.setEnabled(is_fully_viewed)
        self.btn_c2.setEnabled(is_fully_viewed)

        preview_path = listing.get("shown_previews", listing["shown_files"])[cursor]
        pixmap = QPixmap(preview_path)
        self.image_view.set_pixmap(pixmap)

        if full_refresh:
            self.refresh_heavy_blocks()

    def refresh_heavy_blocks(self) -> None:
        if not self.state:
            return

        self.list_labeled.clear()
        labels = self.state["labels"]
        for lid in sorted(labels.keys()):
            item = QListWidgetItem(f"{lid} -> {labels[lid]}")
            item.setData(Qt.UserRole, lid)
            self.list_labeled.addItem(item)

        rows = [
            (lid, str(next(x for x in self.state["listings"] if x["listing_id"] == lid)["shown_indices"]), str(label))
            for lid, label in sorted(labels.items())
        ]
        self.table_overview.setRowCount(len(rows))
        for i, (lid, indices, label) in enumerate(rows):
            self.table_overview.setItem(i, 0, QTableWidgetItem(lid))
            self.table_overview.setItem(i, 1, QTableWidgetItem(indices))
            self.table_overview.setItem(i, 2, QTableWidgetItem(label))

    def next_photo(self) -> None:
        listing = self.current_listing()
        if not listing:
            return
        lid = listing["listing_id"]
        cursor = int(self.state["photo_cursor"].get(lid, 0))
        if cursor >= len(listing["shown_files"]) - 1:
            return
        self.state["photo_cursor"][lid] = cursor + 1
        # no disk I/O on simple navigation
        self.update_ui(full_refresh=False)

    def prev_photo(self) -> None:
        listing = self.current_listing()
        if not listing:
            return
        lid = listing["listing_id"]
        cursor = int(self.state["photo_cursor"].get(lid, 0))
        if cursor <= 0:
            return
        self.state["photo_cursor"][lid] = cursor - 1
        # no disk I/O on simple navigation
        self.update_ui(full_refresh=False)

    def set_label(self, label: int) -> None:
        listing = self.current_listing()
        if not listing:
            return

        lid = listing["listing_id"]
        viewed = set(self.state["viewed_indices"].get(lid, []))
        if len(viewed) != len(listing["shown_files"]):
            self.log("Сначала просмотрите все показываемые фото объявления")
            return

        prev = self.state["labels"].get(lid)
        self.state["labels"][lid] = label
        self.state["actions"].append({"listing_id": lid, "previous_label": prev, "new_label": label})
        self.state["mode"] = "labeling"

        next_id = None
        for item in self.state["listings"]:
            if item["listing_id"] not in self.state["labels"]:
                next_id = item["listing_id"]
                break
        self.state["current_listing_id"] = next_id

        # save only important events
        save_state(self.paths.state_file, self.state)
        save_results(self.paths.results_csv, self.state["labels"], self.state["listings"])

        self.update_ui(full_refresh=True)

    def undo(self) -> None:
        if not self.state or not self.state["actions"]:
            return

        action = self.state["actions"].pop()
        lid = action["listing_id"]
        prev = action["previous_label"]
        if prev is None:
            self.state["labels"].pop(lid, None)
        else:
            self.state["labels"][lid] = prev

        self.state["current_listing_id"] = lid
        self.state["mode"] = "edit"
        listing = next(x for x in self.state["listings"] if x["listing_id"] == lid)
        self.state["photo_cursor"][lid] = len(listing["shown_files"]) - 1
        self.state["viewed_indices"][lid] = list(range(len(listing["shown_files"])))

        save_state(self.paths.state_file, self.state)
        save_results(self.paths.results_csv, self.state["labels"], self.state["listings"])

        self.update_ui(full_refresh=True)

    def open_for_edit(self) -> None:
        if not self.state:
            return
        item = self.list_labeled.currentItem()
        if not item:
            return
        lid = item.data(Qt.UserRole)
        listing = next(x for x in self.state["listings"] if x["listing_id"] == lid)
        self.state["current_listing_id"] = lid
        self.state["mode"] = "edit"
        self.state["viewed_indices"][lid] = list(range(len(listing["shown_files"])))

        save_state(self.paths.state_file, self.state)
        save_results(self.paths.results_csv, self.state["labels"], self.state["listings"])

        self.update_ui(full_refresh=False)


def main() -> None:
    app = QApplication(sys.argv)
    win = LabelingApp()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
