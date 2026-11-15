import datetime
import os
import re
import threading
from functools import partial
from typing import override

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.utils.utilities import ElidedLabel, PopupWidget
from core.validation.widgets.yasb.vscode import VSCodeConfig
from core.widgets.base import BaseWidget
from core.widgets.services.vscode.get_vscode_state_db_path import get_state_db_path
from core.widgets.services.vscode.history import RecentWorkspace, get_history_modified_time, load_recent_workspaces
from core.widgets.services.vscode.labels import describe_remote_authority, workspace_row_text
from core.widgets.services.vscode.launch import launch_vscode


class _FileNameLabel(ElidedLabel):
    """A file name that asks for its full width, so the folder beside it is cut first."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    @override
    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        margins = self.contentsMargins()
        # ElidedLabel keeps 4px spare, so add it back or the full name would elide by a hair.
        hint.setWidth(self.fontMetrics().horizontalAdvance(self.text()) + margins.left() + margins.right() + 4)
        return hint

    @override
    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


class _FitScrollArea(QScrollArea):
    """Asks for its whole list's height, where QScrollArea caps its hint at about 24 lines.

    The menu's CSS max-height still caps the popup, and the list scrolls past that.
    """

    @override
    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        content = self.widget()
        if content is not None:
            hint.setHeight(content.sizeHint().height() + 2 * self.frameWidth())
        return hint


class VSCodeWidget(BaseWidget):
    validation_schema = VSCodeConfig

    def __init__(self, config: VSCodeConfig):
        super().__init__(class_name="vscode-widget")
        self.config = config
        self._show_alt_label = False

        self._state_file_path = self.config.state_storage_path or get_state_db_path()
        self._menu: PopupWidget | None = None
        self._last_db_modified_time: float = 0
        self._active_filter = "all"
        self._search_query = ""
        self._recent_workspaces: list[RecentWorkspace] = []
        self._item_widgets: list[QFrame] = []
        self._no_recents_widget: QLabel | None = None

        self._init_container()
        self.build_widget_label(self.config.label, self.config.label_alt)

        self.register_callback("toggle_label", self._toggle_label)
        self.register_callback("toggle_menu", self._toggle_menu)

        self.callback_left = self.config.callbacks.on_left
        self.callback_right = self.config.callbacks.on_right
        self.callback_middle = self.config.callbacks.on_middle

    def _toggle_menu(self):
        self.show_menu()

    def _toggle_label(self):
        self._show_alt_label = not self._show_alt_label
        for widget in self._widgets:
            widget.setVisible(not self._show_alt_label)
        for widget in self._widgets_alt:
            widget.setVisible(self._show_alt_label)
        self._update_label()

    def _update_label(self):
        active_widgets = self._widgets_alt if self._show_alt_label else self._widgets
        active_label_content = self.config.label_alt if self._show_alt_label else self.config.label
        label_parts = re.split("(<span.*?>.*?</span>)", active_label_content)
        label_parts = [part for part in label_parts if part]
        widget_index = 0

        for part in label_parts:
            part = part.strip()
            if part and widget_index < len(active_widgets):
                if "<span" in part and "</span>" in part:
                    icon = re.sub(r"<span.*?>|</span>", "", part).strip()
                    active_widgets[widget_index].setText(icon)
                else:
                    active_widgets[widget_index].setText(part)
                widget_index += 1

    def _handle_mouse_press_event(self, event: QMouseEvent | None, workspace_data: RecentWorkspace):
        # Off the UI thread: the elevated route waits on Explorer, like shell_open does.
        threading.Thread(
            target=launch_vscode,
            args=(workspace_data, self.config.cli_command, self.config.new_window),
            daemon=True,
        ).start()
        if self._menu is not None:
            self._menu.hide()

    def _bind_container_mouse_press(self, container: QFrame, workspace_data: RecentWorkspace) -> None:
        def mouse_press_event(a0: QMouseEvent | None) -> None:
            self._handle_mouse_press_event(a0, workspace_data)

        container.mousePressEvent = mouse_press_event

    def show_menu(self):
        db_mtime = get_history_modified_time(self._state_file_path)

        if not self._menu:
            self._menu = self._create_popup_menu()
            self._init_menu_layout()

        if db_mtime > self._last_db_modified_time:
            self._refresh_menu_items()
            self._last_db_modified_time = db_mtime

        self._position_and_show_menu()

    def _create_popup_menu(self):
        menu = PopupWidget(
            self,
            self.config.menu.blur,
            self.config.menu.round_corners,
            self.config.menu.round_corners_type,
            self.config.menu.border_color,
            persistent=True,
        )
        menu.setProperty("class", "vscode-menu sections" if self._sections_layout else "vscode-menu")
        return menu

    @property
    def _sections_layout(self) -> bool:
        return self.config.menu_layout == "sections"

    def _init_menu_layout(self):
        self._menu_layout = QVBoxLayout(self._menu)
        self._menu_layout.setSpacing(0)
        self._menu_layout.setContentsMargins(0, 0, 0, 0)

        header_widget = QFrame()
        header_widget.setProperty("class", "header")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)

        header_label = QLabel(self.config.menu_title)
        header_label.setProperty("class", "title")
        header_layout.addWidget(header_label)

        header_layout.addStretch()

        if self._sections_layout:
            if self.config.new_window:
                hint_label = QLabel("opens in a new window")
                hint_label.setProperty("class", "hint")
                header_layout.addWidget(hint_label)
            self._menu_layout.addWidget(header_widget)
        else:
            search_bar = self._init_filters_and_search(header_layout)
            self._menu_layout.addWidget(header_widget)
            self._menu_layout.addWidget(search_bar)

        self._scroll_area = self._create_scroll_area()
        self._menu_layout.addWidget(self._scroll_area)

        self._scroll_widget = QFrame()
        self._scroll_widget.setProperty("class", "contents")
        self._scroll_layout = QVBoxLayout(self._scroll_widget)
        self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(0)

        self._items_layout = QVBoxLayout()
        self._items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(0)
        self._scroll_layout.addLayout(self._items_layout)

        self._no_recents_widget = self._create_no_recents_label()
        self._no_recents_widget.setVisible(False)
        self._scroll_layout.addWidget(self._no_recents_widget)

        self._scroll_area.setWidget(self._scroll_widget)

    def _init_filters_and_search(self, header_layout: QHBoxLayout) -> QFrame:
        """Add the list layout's filter buttons to the header, and return its search bar."""
        self._pill_buttons: dict[str, QPushButton] = {}
        for filter_name in ("all", "folders", "files", "remotes"):
            btn = QPushButton(filter_name.title())
            btn.setProperty("class", "filter-button active" if filter_name == self._active_filter else "filter-button")
            btn.clicked.connect(partial(self._set_filter, filter_name))
            header_layout.addWidget(btn)
            self._pill_buttons[filter_name] = btn

        search_bar = QFrame()
        search_bar.setProperty("class", "search-bar")
        search_bar_layout = QHBoxLayout(search_bar)
        search_bar_layout.setContentsMargins(0, 0, 0, 0)
        search_bar_layout.setSpacing(0)

        self._search_input = QLineEdit()
        self._search_input.setProperty("class", "input")
        self._search_input.setPlaceholderText("Search...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        search_bar_layout.addWidget(self._search_input)

        return search_bar

    def _set_filter(self, filter_name: str, checked: bool = False):
        self._active_filter = filter_name

        for name, btn in self._pill_buttons.items():
            btn.setProperty("class", "filter-button active" if name == filter_name else "filter-button")
            style = btn.style()
            if style is not None:
                style.unpolish(btn)
                style.polish(btn)

        self._refresh_menu_items(reload_db=False)

    def _on_search_changed(self, text: str):
        self._search_query = text.strip().lower()
        self._refresh_menu_items(reload_db=False)

    def _create_scroll_area(self):
        scroll_area = _FitScrollArea() if self._sections_layout else QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setViewportMargins(0, 0, -4, 0)
        scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; border-radius:0; }
            QScrollBar:vertical { border: none; background:transparent; width: 4px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.2); min-height: 10px; border-radius: 2px; }
            QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 0.35); }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        """)
        return scroll_area

    def _create_no_recents_label(self):
        no_recent_label = QLabel("No recent workspaces found.")
        no_recent_label.setProperty("class", "no-recent")
        no_recent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_recent_label.setContentsMargins(0, 20, 0, 20)
        return no_recent_label

    def _create_icon_label(self, workspace_data: RecentWorkspace) -> QLabel | None:
        """The row's icon (remote, folder or file), or None when that icon is set to ""."""
        if workspace_data.get("is_remote", False) and self.config.icons.remote:
            icon_char, icon_class = self.config.icons.remote, "remote-icon"
        elif workspace_data["type"] == "folder":
            icon_char, icon_class = self.config.icons.folder, "folder-icon"
        else:
            icon_char, icon_class = self.config.icons.file, "file-icon"

        if not icon_char:
            return None
        icon_label = QLabel(icon_char)
        icon_label.setProperty("class", icon_class)
        return icon_label

    def _create_workspace_item(self, workspace_data: RecentWorkspace) -> QFrame:
        container = QFrame()
        container.setProperty("class", "item")
        container.setContentsMargins(0, 0, 8, 0)

        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        is_remote = workspace_data.get("is_remote", False)

        icon_label = self._create_icon_label(workspace_data)
        if icon_label is not None:
            container_layout.addWidget(icon_label)

        path = workspace_data["path"]
        display_path = workspace_data["display_path"]
        if self.config.truncate_to_root_dir:
            if is_remote:
                import urllib.parse

                parsed = urllib.parse.urlparse(path)
                remote_path = urllib.parse.unquote(parsed.path).replace("\\", "/").rstrip("/")
                display_path = remote_path.split("/")[-1] if remote_path else "/"
            else:
                local_path = path.replace("\\", "/").rstrip("/")
                if not local_path or local_path.endswith(":"):
                    display_path = path
                else:
                    display_path = local_path.split("/")[-1]

        title_label = ElidedLabel(display_path)
        title_label.setProperty("class", "title")

        if is_remote:
            date_str = describe_remote_authority(workspace_data.get("remote_authority"))
        else:
            try:
                mod_time = os.path.getmtime(path)
                mod_date = datetime.datetime.fromtimestamp(mod_time)
                date_str = mod_date.strftime(self.config.modified_date_format)
            except OSError:
                date_str = "Unknown"

        date_label = ElidedLabel(date_str)
        date_label.setProperty("class", "modified-date")

        text_content = QWidget()
        text_content_layout = QVBoxLayout(text_content)
        text_content_layout.addWidget(title_label)
        text_content_layout.addWidget(date_label)
        text_content_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        text_content_layout.setContentsMargins(0, 0, 0, 0)
        text_content_layout.setSpacing(0)

        container_layout.addWidget(text_content, 1)
        self._bind_container_mouse_press(container, workspace_data)

        return container

    def _create_section_row(self, workspace_data: RecentWorkspace) -> QFrame:
        """A row of the sections layout: name over parent path (folders) or name beside folder (files)."""
        is_folder = workspace_data["type"] == "folder"
        name, detail = workspace_row_text(workspace_data)

        row = QFrame()
        row_classes = ["item", "folder" if is_folder else "file"]
        if workspace_data.get("is_remote", False):
            row_classes.append("remote")
        row.setProperty("class", " ".join(row_classes))
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        icon_label = self._create_icon_label(workspace_data)
        if icon_label is not None:
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(icon_label)

        if is_folder:
            name_label = ElidedLabel(name)
            name_label.setProperty("class", "name")
            path_label = ElidedLabel(detail, elide_mode=Qt.TextElideMode.ElideLeft)
            path_label.setProperty("class", "path")
            if not detail:  # a drive root has no parent path; never setVisible(True) an unparented label
                path_label.hide()

            text_column = QWidget()
            text_layout = QVBoxLayout(text_column)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(0)
            text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            text_layout.addWidget(name_label)
            text_layout.addWidget(path_label)
            row_layout.addWidget(text_column, 1)
        else:
            name_label = _FileNameLabel(name)
            name_label.setProperty("class", "name")
            parent_label = ElidedLabel(detail)
            parent_label.setProperty("class", "parent")
            row_layout.addWidget(name_label)
            row_layout.addWidget(parent_label, 1)

        self._bind_container_mouse_press(row, workspace_data)
        return row

    def _refresh_sections(self):
        """Rebuild the sections layout: Projects (folders), then Recent files, in VS Code's order."""
        for widget in self._item_widgets:
            widget.deleteLater()
        self._item_widgets.clear()

        recent_workspaces = load_recent_workspaces(self._state_file_path)
        folders = [ws for ws in recent_workspaces if ws["type"] == "folder"][: self.config.max_number_of_folders]
        files = [ws for ws in recent_workspaces if ws["type"] == "file"][: self.config.max_number_of_files]
        self._recent_workspaces = folders + files

        def add(widget: QFrame) -> None:
            self._items_layout.addWidget(widget)
            self._item_widgets.append(widget)
            # A polished popup skips children added later, so polish now (with its ancestors in
            # place) or its CSS size only lands after the menu has sized itself.
            widget.ensurePolished()

        for title, workspaces in (("Projects", folders), ("Recent files", files)):
            if not workspaces:
                continue
            if self._item_widgets:
                separator = QFrame()
                separator.setProperty("class", "separator")
                add(separator)
            title_label = QLabel(title)
            title_label.setProperty("class", "section-title")
            add(title_label)
            for workspace in workspaces:
                add(self._create_section_row(workspace))

        if self._no_recents_widget is not None:
            self._no_recents_widget.setVisible(not self._recent_workspaces)

    def _refresh_menu_items(self, reload_db: bool = True):
        if self._sections_layout:
            self._refresh_sections()
            if self._menu is not None:
                self._menu.adjustSize()
            return

        if reload_db:
            for widget in self._item_widgets:
                widget.deleteLater()
            self._item_widgets.clear()

            recent_workspaces = load_recent_workspaces(self._state_file_path)
            if recent_workspaces:
                folders = [ws for ws in recent_workspaces if ws["type"] == "folder"][
                    : self.config.max_number_of_folders
                ]
                files = [ws for ws in recent_workspaces if ws["type"] == "file"][: self.config.max_number_of_files]
                self._recent_workspaces = folders + files
            else:
                self._recent_workspaces = []

            for workspace in self._recent_workspaces:
                item_widget = self._create_workspace_item(workspace)
                item_widget.setProperty("workspace_type", workspace["type"])
                item_widget.setProperty("is_remote", workspace.get("is_remote", False))
                item_widget.setProperty("display_path", workspace.get("display_path", ""))
                item_widget.setProperty("path", workspace.get("path", ""))
                self._items_layout.addWidget(item_widget)
                self._item_widgets.append(item_widget)

        search_query = self._search_query.lower()

        has_visible_items = False
        for item_widget in self._item_widgets:
            w_type = item_widget.property("workspace_type")
            w_remote = item_widget.property("is_remote")
            display_path = item_widget.property("display_path") or ""
            path = item_widget.property("path") or ""

            visible = True
            if self._active_filter == "folders" and w_type != "folder":
                visible = False
            elif self._active_filter == "files" and w_type != "file":
                visible = False
            elif self._active_filter == "remotes" and not w_remote:
                visible = False

            if visible and search_query:
                haystack = (display_path + path).lower()
                if search_query not in haystack:
                    visible = False

            item_widget.setVisible(visible)
            if visible:
                has_visible_items = True

        show_empty = (not self._recent_workspaces) or (not has_visible_items)
        if self._no_recents_widget is not None:
            self._no_recents_widget.setVisible(show_empty)

        if self._menu is not None:
            self._menu.adjustSize()

    def _position_and_show_menu(self):
        menu = self._menu
        if menu is None:
            return
        menu.adjustSize()
        menu.setPosition(
            alignment=self.config.menu.alignment,
            direction=self.config.menu.direction,
            offset_left=self.config.menu.offset_left,
            offset_top=self.config.menu.offset_top,
        )
        menu.show()
