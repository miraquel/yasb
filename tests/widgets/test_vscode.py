# pyright: reportPrivateUsage=false

import json
import sqlite3
import subprocess
import weakref
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, override

import pytest
from pydantic import ValidationError
from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QLineEdit, QPushButton, QWidget

from core.utils.utilities import ElidedLabel
from core.utils.win32.constants import SW_HIDE, SW_SHOWNORMAL, SWC_DESKTOP, SWFO_NEEDDISPATCH
from core.validation.widgets.yasb.vscode import VSCodeConfig
from core.widgets.services.vscode import launch
from core.widgets.services.vscode.history import RecentWorkspace
from core.widgets.services.vscode.labels import describe_remote_authority, split_local_path, workspace_row_text
from core.widgets.services.vscode.launch import build_launch_args, launch_vscode, resolve_launch_target
from core.widgets.yasb import vscode
from core.widgets.yasb.vscode import VSCodeWidget

type MakeMenu = Callable[..., VSCodeWidget]


def _local(kind: str, path: str) -> RecentWorkspace:
    return {"type": kind, "path": path, "display_path": path, "is_remote": False}


def _remote(kind: str, uri: str, authority: str | None, display_path: str = "") -> RecentWorkspace:
    return {
        "type": kind,
        "path": uri,
        "display_path": display_path or uri,
        "is_remote": True,
        "remote_authority": authority,
    }


RECENTS: list[RecentWorkspace] = [
    _local("folder", "D:/Work/geisab2b"),
    _local("file", "D:/notes/a/START-HERE.md"),
    _local("folder", "D:/PROJECTFILE/Iwan/yasb"),
    _remote("folder", "vscode-remote://wsl%2BUbuntu/home/iwan/site", "wsl+Ubuntu", "WSL: Ubuntu - /home/iwan/site"),
    _local("file", "D:/notes/b/parity.md"),
]

VSCODE_DIR = r"C:\Users\me\AppData\Local\Programs\Microsoft VS Code"


def _classes(widget: QWidget) -> list[str]:
    return str(widget.property("class") or "").split()


def _build(widget: VSCodeWidget) -> VSCodeWidget:
    widget._menu = widget._create_popup_menu()
    widget._init_menu_layout()
    widget._refresh_menu_items()
    return widget


@pytest.fixture
def make_menu(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[MakeMenu]:
    """A VS Code widget with its popup built (never shown), reading ``recents`` instead of VS Code's database."""
    widgets: list[VSCodeWidget] = []

    def make(recents: list[RecentWorkspace], **options: Any) -> VSCodeWidget:
        def load_recent_workspaces(state_file_path: str) -> list[RecentWorkspace]:
            return recents

        monkeypatch.setattr(vscode, "load_recent_workspaces", load_recent_workspaces)
        widget = VSCodeWidget(VSCodeConfig.model_validate({"state_storage_path": "unused.vscdb", **options}))
        widgets.append(widget)
        return _build(widget)

    yield make
    for widget in widgets:
        if widget._menu is not None:
            widget._menu.close()
        widget.close()


def _menu(widget: VSCodeWidget) -> QWidget:
    assert widget._menu is not None
    return widget._menu


def _contents_children(widget: VSCodeWidget) -> list[QWidget]:
    """The section titles, separators and rows, in the order they appear."""
    contents = next(f for f in _menu(widget).findChildren(QFrame) if "contents" in _classes(f))
    direct = contents.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
    return [w for w in direct if {"section-title", "separator", "item"} & set(_classes(w))]


def _row_labels(row: QWidget) -> dict[str, QLabel]:
    return {_classes(label)[0]: label for label in row.findChildren(QLabel)}


def _describe(widget: QWidget) -> str:
    if "section-title" in _classes(widget):
        assert isinstance(widget, QLabel)
        return f"title:{widget.text()}"
    if "separator" in _classes(widget):
        return "separator"
    return f"{_classes(widget)[1]}:{_row_labels(widget)['name'].text()}"


def _left_click() -> QMouseEvent:
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


# --- config ----------------------------------------------------------------------------


def test_the_new_options_default_to_todays_behaviour():
    config = VSCodeConfig()

    assert config.menu_layout == "list"
    assert config.new_window is False


def test_an_unknown_layout_is_rejected():
    with pytest.raises(ValidationError):
        VSCodeConfig.model_validate({"menu_layout": "grid"})


def test_the_deprecated_icon_options_still_migrate():
    config = VSCodeConfig.model_validate({"folder_icon": "F", "hide_file_icon": True, "menu_layout": "sections"})

    assert (config.icons.folder, config.icons.file) == ("F", "")


# --- row text --------------------------------------------------------------------------


def test_a_path_splits_into_its_name_and_a_backslashed_parent():
    # history.py hands over forward slashes (it decodes file:// URIs).
    assert split_local_path("D:/PROJECTFILE/Iwan/yasb") == ("yasb", "D:\\PROJECTFILE\\Iwan")


def test_a_trailing_separator_is_ignored():
    assert split_local_path("D:/PROJECTFILE/Iwan/yasb/") == ("yasb", "D:\\PROJECTFILE\\Iwan")
    assert split_local_path("D:\\PROJECTFILE\\Iwan\\yasb\\") == ("yasb", "D:\\PROJECTFILE\\Iwan")


def test_a_folder_directly_under_a_drive_keeps_the_drive_as_parent():
    assert split_local_path("D:/Android") == ("Android", "D:\\")


@pytest.mark.parametrize("root", ["D:/", "D:\\", "D:"])
def test_a_drive_root_is_its_own_name_with_no_parent(root: str):
    assert split_local_path(root) == ("D:\\", "")


def test_a_unc_share_folder_keeps_the_share_as_parent():
    assert split_local_path("\\\\server\\share\\proj") == ("proj", "\\\\server\\share\\")


@pytest.mark.parametrize(
    ("authority", "described"),
    [
        ("wsl+Ubuntu-24.04", "WSL (Ubuntu-24.04)"),
        ("ssh-remote+devbox", "SSH (devbox)"),
        ("dev-container+7b22686f737450617468", "Dev Container"),
        ("wsl+", "WSL Connection"),
        ("ssh-remote+", "SSH Connection"),
        ("tunnel+box", "Remote: tunnel+box"),
        ("", "Remote Connection"),
        (None, "Remote Connection"),
    ],
)
def test_remote_authorities_are_described_by_their_connection(authority: str | None, described: str):
    assert describe_remote_authority(authority) == described


@pytest.mark.parametrize(
    ("workspace", "row_text"),
    [
        (
            _local("folder", "D:/Work/SQLSERVERMS/Visual Studio Code/geisab2b"),
            ("geisab2b", "D:\\Work\\SQLSERVERMS\\Visual Studio Code"),
        ),
        (_local("folder", "D:/"), ("D:\\", "")),
        (
            _local("file", "D:/PROJECTFILE/prod-switch-geisab2b-api/parity-report.md"),
            ("parity-report.md", "prod-switch-geisab2b-api"),
        ),
        (_local("file", "D:/notes.txt"), ("notes.txt", "D:\\")),
        (
            _remote("folder", "vscode-remote://wsl%2BUbuntu/home/iwan/my%20proj", "wsl+Ubuntu"),
            ("my proj", "WSL (Ubuntu)"),
        ),
        (
            _remote("folder", "vscode-remote://ssh-remote%2Bdevbox/srv/app/", "ssh-remote+devbox"),
            ("app", "SSH (devbox)"),
        ),
        (_remote("folder", "vscode-remote://ssh-remote%2Bdevbox/", "ssh-remote+devbox"), ("/", "SSH (devbox)")),
        # No remoteAuthority in VS Code's entry: the connection comes from the URI.
        (_remote("folder", "vscode-remote://wsl%2BDebian/home/iwan/site", None), ("site", "WSL (Debian)")),
        (
            _remote("file", "vscode-remote://wsl%2BUbuntu/home/iwan/proj/README.md", "wsl+Ubuntu"),
            ("README.md", "proj · WSL (Ubuntu)"),
        ),
    ],
)
def test_a_row_shows_a_name_and_where_it_lives(workspace: RecentWorkspace, row_text: tuple[str, str]):
    assert workspace_row_text(workspace) == row_text


# --- the launch command line -----------------------------------------------------------

LOCAL_FOLDER = _local("folder", "D:/PROJECTFILE/Iwan/yasb")
LOCAL_FILE = _local("file", "D:/notes/todo.md")
REMOTE_FOLDER = _remote("folder", "vscode-remote://wsl%2BUbuntu/home/iwan/proj", "wsl+Ubuntu")
REMOTE_FILE = _remote("file", "vscode-remote://ssh-remote%2Bbox/etc/hosts", "ssh-remote+box")


@pytest.mark.parametrize(
    ("workspace", "new_window", "args"),
    [
        (LOCAL_FOLDER, False, [LOCAL_FOLDER["path"]]),
        (LOCAL_FILE, False, [LOCAL_FILE["path"]]),
        (REMOTE_FOLDER, False, ["--folder-uri", REMOTE_FOLDER["path"]]),
        (REMOTE_FILE, False, ["--file-uri", REMOTE_FILE["path"]]),
        (LOCAL_FOLDER, True, ["--new-window", LOCAL_FOLDER["path"]]),
        (LOCAL_FILE, True, ["--new-window", LOCAL_FILE["path"]]),
        (REMOTE_FOLDER, True, ["--new-window", "--folder-uri", REMOTE_FOLDER["path"]]),
        (REMOTE_FILE, True, ["--new-window", "--file-uri", REMOTE_FILE["path"]]),
    ],
)
def test_launch_arguments(workspace: RecentWorkspace, new_window: bool, args: list[str]):
    assert build_launch_args(workspace, new_window) == args


def test_code_cmd_resolves_to_the_gui_exe_one_level_up():
    # shutil.which spells the extension the way PATHEXT does, so ".CMD" is what really comes back.
    cmd = VSCODE_DIR + r"\bin\code.CMD"
    exe = VSCODE_DIR + r"\Code.exe"

    assert resolve_launch_target("code", which=lambda _: cmd, isfile=lambda p: p == exe) == (exe, SW_SHOWNORMAL)


def test_code_cmd_without_a_sibling_exe_runs_the_cli_hidden():
    cmd = VSCODE_DIR + r"\bin\code.cmd"

    assert resolve_launch_target("code", which=lambda _: cmd, isfile=lambda _: False) == (cmd, SW_HIDE)


def test_other_scripts_run_hidden():
    cmd = r"C:\Programs\Microsoft VS Code Insiders\bin\code-insiders.cmd"

    assert resolve_launch_target("code-insiders", which=lambda _: cmd, isfile=lambda _: True) == (cmd, SW_HIDE)


def test_an_exe_runs_shown():
    exe = r"D:\Tools\VSCodium\VSCodium.exe"

    assert resolve_launch_target(exe, which=lambda _: exe, isfile=lambda _: True) == (exe, SW_SHOWNORMAL)


def test_an_unresolved_command_is_left_to_the_shell_hidden():
    assert resolve_launch_target("code", which=lambda _: None, isfile=lambda _: False) == ("code", SW_HIDE)


# --- elevated or not -------------------------------------------------------------------


class _Launches:
    def __init__(self) -> None:
        self.shell: list[tuple[str, str, str, int]] = []
        self.popen: list[tuple[list[str], dict[str, object]]] = []
        self.shell_error: Exception | None = None
        self.popen_error: Exception | None = None


@pytest.fixture
def launches(monkeypatch: pytest.MonkeyPatch) -> _Launches:
    """Records both launch routes instead of starting anything."""
    recorded = _Launches()

    def shell_execute_unelevated(file: str, parameters: str, directory: str, show: int) -> None:
        if recorded.shell_error is not None:
            raise recorded.shell_error
        recorded.shell.append((file, parameters, directory, show))

    def popen(args: list[str], **kwargs: object) -> None:
        if recorded.popen_error is not None:
            raise recorded.popen_error
        recorded.popen.append((args, kwargs))

    def resolve(cli_command: str) -> tuple[str, int]:
        return VSCODE_DIR + r"\Code.exe", SW_SHOWNORMAL

    monkeypatch.setattr(launch, "shell_execute_unelevated", shell_execute_unelevated)
    monkeypatch.setattr(launch, "resolve_launch_target", resolve)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setenv("USERPROFILE", r"C:\Users\me")
    return recorded


def _set_elevated(monkeypatch: pytest.MonkeyPatch, elevated: bool) -> None:
    def is_user_an_admin() -> bool:
        return elevated

    monkeypatch.setattr(launch, "IsUserAnAdmin", is_user_an_admin)


def test_elevated_goes_through_the_desktop_shell(monkeypatch: pytest.MonkeyPatch, launches: _Launches):
    _set_elevated(monkeypatch, True)

    launch_vscode(REMOTE_FOLDER, "code", new_window=True)

    assert launches.shell == [
        (
            VSCODE_DIR + r"\Code.exe",
            "--new-window --folder-uri vscode-remote://wsl%2BUbuntu/home/iwan/proj",
            r"C:\Users\me",
            SW_SHOWNORMAL,
        )
    ]
    assert launches.popen == []


def test_shell_parameters_quote_paths_with_spaces(monkeypatch: pytest.MonkeyPatch, launches: _Launches):
    _set_elevated(monkeypatch, True)

    launch_vscode(_local("folder", "D:/Visual Studio Code/app"), "code", new_window=False)

    assert launches.shell[0][1] == '"D:/Visual Studio Code/app"'


def test_not_elevated_keeps_the_popen_route(monkeypatch: pytest.MonkeyPatch, launches: _Launches):
    _set_elevated(monkeypatch, False)

    launch_vscode(LOCAL_FOLDER, "code", new_window=False)

    assert launches.shell == []
    assert launches.popen == [
        (
            ["code", "D:/PROJECTFILE/Iwan/yasb"],
            {
                "shell": True,
                "creationflags": subprocess.CREATE_NO_WINDOW,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            },
        )
    ]


def test_a_shell_failure_falls_back_to_popen_and_logs(
    monkeypatch: pytest.MonkeyPatch, launches: _Launches, caplog: pytest.LogCaptureFixture
):
    _set_elevated(monkeypatch, True)
    launches.shell_error = OSError("no desktop shell")

    with caplog.at_level("WARNING"):
        launch_vscode(LOCAL_FILE, "code", new_window=True)

    assert [args for args, _ in launches.popen] == [["code", "--new-window", "D:/notes/todo.md"]]
    assert "no desktop shell" in caplog.text


def test_a_popen_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch, launches: _Launches, caplog: pytest.LogCaptureFixture
):
    _set_elevated(monkeypatch, False)
    launches.popen_error = FileNotFoundError("code")

    with caplog.at_level("ERROR"):
        launch_vscode(LOCAL_FOLDER, "code", new_window=False)

    assert "Failed to open VS Code" in caplog.text


# --- the desktop shell call ------------------------------------------------------------


class _FakeShellApp:
    """Explorer's IShellDispatch2, reached as desktop.Document.Application."""

    def __init__(self, calls: list[tuple[object, ...]], error: Exception | None) -> None:
        self._calls = calls
        self._error = error

    def ShellExecute(self, *args: object) -> None:
        if self._error is not None:
            raise self._error
        self._calls.append(args)


class _FakeDesktop:
    def __init__(self, app: _FakeShellApp) -> None:
        self.Document = SimpleNamespace(Application=app)


class _FakeShellWindows:
    def __init__(self, desktop: _FakeDesktop | None, finds: list[tuple[object, ...]]) -> None:
        self._desktop = desktop
        self._finds = finds

    def FindWindowSW(self, *args: object) -> _FakeDesktop | None:
        self._finds.append(args)
        return self._desktop


class _FakeShell:
    """Stands in for create_dispatch("Shell.Application"); records what Explorer would be asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, desktop_found: bool = True) -> None:
        self.finds: list[tuple[object, ...]] = []
        self.executes: list[tuple[object, ...]] = []
        self.error: Exception | None = None
        self.desktops: list[weakref.ref[_FakeDesktop]] = []
        self.uninitialised_with_desktop_alive: list[bool] = []
        self._desktop_found = desktop_found
        monkeypatch.setattr(launch, "create_dispatch", self._create_dispatch)
        monkeypatch.setattr(launch, "CoInitialize", self._co_initialize)
        monkeypatch.setattr(launch, "CoUninitialize", self._co_uninitialize)

    def _create_dispatch(self, progid: str) -> SimpleNamespace:
        assert progid == "Shell.Application"
        desktop = _FakeDesktop(_FakeShellApp(self.executes, self.error)) if self._desktop_found else None
        if desktop is not None:
            self.desktops.append(weakref.ref(desktop))
        shell_windows = _FakeShellWindows(desktop, self.finds)

        def windows() -> _FakeShellWindows:
            return shell_windows

        return SimpleNamespace(Windows=windows)

    def _co_initialize(self) -> int:
        return 0

    def _co_uninitialize(self) -> None:
        self.uninitialised_with_desktop_alive.append(any(ref() is not None for ref in self.desktops))


def test_the_desktop_window_is_asked_to_shell_execute(monkeypatch: pytest.MonkeyPatch):
    shell = _FakeShell(monkeypatch)

    launch.shell_execute_unelevated(r"C:\VS Code\Code.exe", "--new-window D:/p", r"C:\Users\me", SW_SHOWNORMAL)

    assert shell.finds == [(0, 0, SWC_DESKTOP, 0, SWFO_NEEDDISPATCH)]
    assert shell.executes == [(r"C:\VS Code\Code.exe", "--new-window D:/p", r"C:\Users\me", "open", SW_SHOWNORMAL)]
    assert shell.uninitialised_with_desktop_alive == [False]


def test_no_desktop_window_is_an_error(monkeypatch: pytest.MonkeyPatch):
    shell = _FakeShell(monkeypatch, desktop_found=False)

    with pytest.raises(OSError, match="desktop shell window"):
        launch.shell_execute_unelevated("Code.exe", "", r"C:\Users\me", SW_SHOWNORMAL)
    assert shell.uninitialised_with_desktop_alive == [False]


def test_a_failed_shell_call_releases_its_com_objects_before_com_is_uninitialised(monkeypatch: pytest.MonkeyPatch):
    # The traceback keeps the failed call's frames, and with them its COM objects; releasing
    # those after CoUninitialize would call into a torn-down apartment.
    shell = _FakeShell(monkeypatch)
    shell.error = OSError("access denied")

    with pytest.raises(OSError, match="access denied"):
        launch.shell_execute_unelevated("Code.exe", "", r"C:\Users\me", SW_SHOWNORMAL)
    assert shell.uninitialised_with_desktop_alive == [False]


# --- the sections layout ---------------------------------------------------------------


def test_projects_come_before_recent_files_in_recency_order(make_menu: MakeMenu):
    widget = make_menu(RECENTS, menu_layout="sections", max_number_of_folders=2, max_number_of_files=5)

    assert [_describe(w) for w in _contents_children(widget)] == [
        "title:Projects",
        "folder:geisab2b",
        "folder:yasb",
        "separator",
        "title:Recent files",
        "file:START-HERE.md",
        "file:parity.md",
    ]


def test_sections_are_read_from_vscodes_state_database(qapp: QApplication, tmp_path: Path):
    project = tmp_path / "work" / "yasb"
    project.mkdir(parents=True)
    note = tmp_path / "notes" / "todo.md"
    note.parent.mkdir()
    note.write_text("x", encoding="utf-8")
    entries = [
        {"folderUri": project.as_uri()},
        {"fileUri": note.as_uri()},
        {"folderUri": (tmp_path / "deleted").as_uri()},
        {"folderUri": "vscode-remote://wsl%2BUbuntu/home/iwan/site", "remoteAuthority": "wsl+Ubuntu"},
    ]
    state_db = tmp_path / "state.vscdb"
    conn = sqlite3.connect(state_db)
    try:
        conn.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
        conn.execute(
            "INSERT INTO ItemTable VALUES (?, ?)",
            ("history.recentlyOpenedPathsList", json.dumps({"entries": entries})),
        )
        conn.commit()
    finally:
        conn.close()

    widget = _build(VSCodeWidget(VSCodeConfig(menu_layout="sections", state_storage_path=str(state_db))))

    # A folder that no longer exists is left out, the remote one stays.
    assert [_describe(w) for w in _contents_children(widget)] == [
        "title:Projects",
        "folder:yasb",
        "folder:site",
        "separator",
        "title:Recent files",
        "file:todo.md",
    ]
    widget.close()


def test_the_sections_layout_has_no_filter_buttons_or_search(make_menu: MakeMenu):
    widget = make_menu(RECENTS, menu_layout="sections")

    assert _menu(widget).findChildren(QPushButton) == []
    assert _menu(widget).findChildren(QLineEdit) == []
    assert "sections" in _classes(_menu(widget))


@pytest.mark.parametrize(("new_window", "hints"), [(True, ["opens in a new window"]), (False, [])])
def test_the_header_hint_shows_only_with_new_window(make_menu: MakeMenu, new_window: bool, hints: list[str]):
    widget = make_menu(RECENTS, menu_layout="sections", new_window=new_window)

    assert [label.text() for label in _menu(widget).findChildren(QLabel) if "hint" in _classes(label)] == hints


def test_a_folder_row_puts_the_name_over_a_left_elided_parent_path(make_menu: MakeMenu):
    widget = make_menu(RECENTS[:1], menu_layout="sections")
    labels = _row_labels(_contents_children(widget)[1])

    assert labels["name"].text() == "geisab2b"
    assert labels["path"].text() == "D:\\Work"
    path_label = labels["path"]
    assert isinstance(path_label, ElidedLabel)
    assert path_label.elide_mode == Qt.TextElideMode.ElideLeft
    assert labels["folder-icon"].text() == widget.config.icons.folder


def test_a_remote_folder_row_describes_the_connection(make_menu: MakeMenu):
    widget = make_menu([RECENTS[3]], menu_layout="sections")
    row = _contents_children(widget)[1]
    labels = _row_labels(row)

    assert (labels["name"].text(), labels["path"].text()) == ("site", "WSL (Ubuntu)")
    assert _classes(row) == ["item", "folder", "remote"]


def test_a_file_row_shows_its_name_and_parent_folder(make_menu: MakeMenu):
    widget = make_menu([RECENTS[1]], menu_layout="sections")
    labels = _row_labels(_contents_children(widget)[1])

    assert (labels["name"].text(), labels["parent"].text()) == ("START-HERE.md", "a")
    assert "file-icon" in labels


def test_an_empty_section_is_left_out(make_menu: MakeMenu):
    folders_only = make_menu([RECENTS[0]], menu_layout="sections")
    files_only = make_menu([RECENTS[1]], menu_layout="sections")

    assert [_describe(w) for w in _contents_children(folders_only)] == ["title:Projects", "folder:geisab2b"]
    assert [_describe(w) for w in _contents_children(files_only)] == ["title:Recent files", "file:START-HERE.md"]


def test_no_recents_shows_the_empty_label(make_menu: MakeMenu):
    widget = make_menu([], menu_layout="sections")

    assert _contents_children(widget) == []
    assert widget._no_recents_widget is not None
    assert not widget._no_recents_widget.isHidden()


def test_the_menu_asks_for_the_whole_list_height(make_menu: MakeMenu):
    # QScrollArea caps its own size hint at about 24 lines, which cut the list off at ~320px.
    # The sections menu asks for everything; the menu's max-height (CSS) is what caps it.
    many = [_local("folder", f"D:/Work/p{i}") for i in range(30)]
    widget = make_menu(many, menu_layout="sections", max_number_of_folders=30)
    content = widget._scroll_area.widget()
    assert content is not None
    list_height = content.sizeHint().height()

    assert list_height > 500
    assert widget._scroll_area.sizeHint().height() >= list_height
    assert _menu(widget).sizeHint().height() > list_height


def test_css_sizes_count_before_the_menu_sizes_itself(qapp: QApplication, monkeypatch: pytest.MonkeyPatch):
    # An already-polished popup does not polish children added later, so a separator's CSS
    # height would only arrive after the menu was sized, squeezing the rows above it.
    def load_recent_workspaces(state_file_path: str) -> list[RecentWorkspace]:
        return RECENTS

    monkeypatch.setattr(vscode, "load_recent_workspaces", load_recent_workspaces)
    widget = VSCodeWidget(VSCodeConfig(menu_layout="sections", state_storage_path="unused.vscdb"))
    widget._menu = widget._create_popup_menu()
    widget._menu.setStyleSheet(".separator { min-height: 20px; max-height: 20px; }")
    widget._init_menu_layout()
    widget._menu.ensurePolished()

    widget._refresh_menu_items()

    separator = next(w for w in _contents_children(widget) if "separator" in _classes(w))
    assert separator.minimumHeight() == 20
    widget.close()


class _ShowSpy(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.shown: list[QWidget] = []

    @override
    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a1 is not None and a1.type() == QEvent.Type.Show and isinstance(a0, QWidget) and a0.isWindow():
            self.shown.append(a0)
        return False


def test_building_rows_never_shows_a_window(qapp: QApplication, make_menu: MakeMenu):
    # setVisible(True) on a label that has no parent yet shows it as its own top-level window.
    spy = _ShowSpy()
    qapp.installEventFilter(spy)
    try:
        make_menu(RECENTS + [_local("folder", "D:/")], menu_layout="sections")
    finally:
        qapp.removeEventFilter(spy)

    assert spy.shown == []


# --- clicking a row --------------------------------------------------------------------


class _InlineThread:
    def __init__(self, target: Callable[..., None], args: tuple[object, ...] = (), daemon: bool = False) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[tuple[RecentWorkspace, str, bool]]:
    calls: list[tuple[RecentWorkspace, str, bool]] = []

    def launch_vscode(workspace: RecentWorkspace, cli_command: str, new_window: bool) -> None:
        calls.append((workspace, cli_command, new_window))

    monkeypatch.setattr(vscode, "threading", SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(vscode, "launch_vscode", launch_vscode)
    return calls


def test_clicking_a_section_row_opens_it_with_the_new_window_option(
    make_menu: MakeMenu, opened: list[tuple[RecentWorkspace, str, bool]]
):
    widget = make_menu(RECENTS[:1], menu_layout="sections", new_window=True, cli_command="codium")

    _contents_children(widget)[1].mousePressEvent(_left_click())

    assert opened == [(RECENTS[0], "codium", True)]


def test_clicking_a_list_row_goes_through_the_same_launcher(
    make_menu: MakeMenu, opened: list[tuple[RecentWorkspace, str, bool]]
):
    widget = make_menu(RECENTS[:1])

    widget._item_widgets[0].mousePressEvent(_left_click())

    assert opened == [(RECENTS[0], "code", False)]


# --- ElidedLabel -----------------------------------------------------------------------


def test_eliding_fits_the_content_box_so_a_css_margin_does_not_clip_the_ellipsis(qapp: QApplication):
    label = ElidedLabel()
    label.setContentsMargins(30, 0, 0, 0)  # what a CSS margin-left does to a QLabel
    label.resize(110, 20)
    label.setText("prod-switch-geisab2b-api")

    shown = QLabel.text(label)
    assert shown.endswith("…"), shown
    assert label.fontMetrics().horizontalAdvance(shown) <= label.contentsRect().width()


def test_left_elision_keeps_the_tail(qapp: QApplication):
    label = ElidedLabel(elide_mode=Qt.TextElideMode.ElideLeft)
    label.resize(90, 20)
    path = "D:\\PROJECTFILE\\PROJECT_BELAJAR\\DPRINCES"
    label.setText(path)

    # How much fits depends on the font, so check the shape: an ellipsis, then the path's tail.
    shown = QLabel.text(label)
    assert shown.startswith("…") and len(shown) > 1 and path.endswith(shown[1:]), shown


# --- the list layout -------------------------------------------------------------------


def test_the_default_layout_keeps_its_filters_and_search(make_menu: MakeMenu):
    widget = make_menu(RECENTS)

    assert [b.text() for b in _menu(widget).findChildren(QPushButton)] == ["All", "Folders", "Files", "Remotes"]
    assert len(_menu(widget).findChildren(QLineEdit)) == 1
    assert _classes(_menu(widget)) == ["vscode-menu"]
    titles = [label.text() for label in _menu(widget).findChildren(QLabel) if _classes(label) == ["title"]]
    assert "D:/Work/geisab2b" in titles


def test_a_list_row_describes_a_remote_connection(make_menu: MakeMenu):
    widget = make_menu([RECENTS[3]])

    dates = [label.text() for label in _menu(widget).findChildren(QLabel) if _classes(label) == ["modified-date"]]
    assert dates == ["WSL (Ubuntu)"]
