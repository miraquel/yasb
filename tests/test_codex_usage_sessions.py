# pyright: reportPrivateUsage=false

"""Tests for reading live Codex sessions from Codex's own files.

Each test builds a throwaway Codex home: the two SQLite databases with only the columns the
reader uses, and an empty lock file per thread. Whether a lock is held is chosen per test with
``probe``, except in the one test that holds a real lock, so nothing here depends on what Codex
is doing on the machine.
"""

import json
import msvcrt
import os
import sqlite3
import sys
import tempfile
import unittest
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.validation.widgets.yasb.codex_usage import CodexUsageConfig  # noqa: E402
from core.widgets.services.codex_usage import sessions as sessions_module  # noqa: E402
from core.widgets.services.codex_usage.sessions import (  # noqa: E402
    LOCK_MISSING,
    LOCK_OPEN,
    LOCK_STALE,
    app_hint,
    latest_db,
    lock_state,
    read_codex_sessions,
    read_marker,
    turn_events,
)

NOW = 1_800_000_000.0
_THREAD_COLUMNS = ("id", "name", "title", "cwd", "source", "originator", "thread_source", "updated_at", "archived")


def thread(thread_id: str, **fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": None,
        "title": "",
        "cwd": "",
        "source": "cli",
        "originator": None,
        "thread_source": "user",
    }
    row.update(updated_at=0, archived=0, id=thread_id)
    row.update(fields)
    return row


Turn = tuple[str, str, str, int, int | None]


def turn(thread_id: str, turn_id: str, status: str, started_at: float, completed_at: float | None = None) -> Turn:
    return (thread_id, turn_id, status, int(started_at), None if completed_at is None else int(completed_at))


def make_home(
    root: Path,
    threads: Iterable[dict[str, Any]],
    turns: Iterable[Turn],
    items: Iterable[tuple[str, str, int, int | None]] = (),
    edges: Iterable[tuple[str, str]] = (),
    versions: tuple[int, int] = (5, 1),
) -> Path:
    """A Codex home with ``state_<v>.sqlite``, ``thread_history_<v>.sqlite`` and a lock per thread."""
    home = root / "codex"
    (home / "thread-writer-locks").mkdir(parents=True)
    state = sqlite3.connect(home / f"state_{versions[0]}.sqlite")
    state.execute(f"create table threads ({', '.join(_THREAD_COLUMNS)})")
    state.execute("create table thread_spawn_edges (parent_thread_id, child_thread_id, status)")
    for row in threads:
        state.execute(
            f"insert into threads values ({', '.join('?' * len(_THREAD_COLUMNS))})", [row[c] for c in _THREAD_COLUMNS]
        )
        (home / "thread-writer-locks" / f"{row['id']}.lock").write_bytes(b"")
    state.executemany("insert into thread_spawn_edges values (?, ?, 'open')", edges)
    state.commit()
    state.close()
    history = sqlite3.connect(home / f"thread_history_{versions[1]}.sqlite")
    history.execute("create table thread_turns (thread_id, turn_id, rollout_ordinal, status, started_at, completed_at)")
    history.execute("create table thread_items (thread_id, turn_id, created_at_ms, started_at_ms, completed_at_ms)")
    for ordinal, (thread_id, turn_id, status, started, completed) in enumerate(turns):
        history.execute(
            "insert into thread_turns values (?, ?, ?, ?, ?, ?)",
            (thread_id, turn_id, ordinal, status, started, completed),
        )
    for thread_id, turn_id, started_ms, completed_ms in items:
        history.execute(
            "insert into thread_items values (?, ?, ?, ?, ?)",
            (thread_id, turn_id, started_ms, started_ms, completed_ms),
        )
    history.commit()
    history.close()
    return home


def probe(**states: str) -> Callable[[str], str]:
    """A lock probe that reports the given state per thread id, and stale for the rest."""
    return lambda path: states.get(Path(path).stem, LOCK_STALE)


class CodexSessionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.markers = self.root / "markers"
        self.markers.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def read(self, home: Path, idle_minutes: int = 30, items_live: bool = True, **states: str) -> list[dict[str, Any]]:
        sessions = read_codex_sessions(
            str(home), str(self.markers), NOW, idle_minutes, probe=probe(**states), items_live=items_live
        )
        assert sessions is not None
        return sessions

    def mark(self, thread_id: str, turn_id: str, tool: str = "shell", at_ms: int = int(NOW * 1000) - 5000) -> None:
        marker = {"turn_id": turn_id, "tool_name": tool, "at_ms": at_ms}
        (self.markers / f"{thread_id}.json").write_text(json.dumps(marker), encoding="utf-8")

    def test_latest_db_picks_highest_version(self):
        home = self.root / "codex"
        home.mkdir()
        for name in ("state_5.sqlite", "state_12.sqlite", "state_7.sqlite", "state_x.sqlite"):
            (home / name).write_bytes(b"")
        latest = latest_db(str(home), "state")
        assert latest is not None
        self.assertTrue(latest.endswith("state_12.sqlite"))
        self.assertIsNone(latest_db(str(home), "thread_history"))

    def test_lock_state_reads_held_lock_as_open(self):
        path = self.root / "a.lock"
        path.write_bytes(b"")
        fd = os.open(path, os.O_RDWR)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            self.assertEqual(lock_state(str(path)), LOCK_OPEN)
            os.lseek(fd, 0, 0)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)
        self.assertEqual(lock_state(str(path)), LOCK_STALE)
        path.unlink()
        self.assertEqual(lock_state(str(path)), LOCK_MISSING)

    def test_open_thread_with_turn_in_progress_is_working(self):
        home = make_home(self.root, [thread("t1", title="fix tests")], [turn("t1", "u1", "inProgress", NOW - 20)])
        sessions = self.read(home, t1=LOCK_OPEN)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(
            (sessions[0]["session_id"], sessions[0]["status"], sessions[0]["turn_status"]),
            ("t1", "working", "inProgress"),
        )
        self.assertEqual(sessions[0]["name"], "fix tests")

    def test_stale_lock_never_counts(self):
        home = make_home(self.root, [thread("t1")], [turn("t1", "u1", "inProgress", NOW - 20)])
        self.assertEqual(self.read(home, t1=LOCK_STALE), [])

    def test_idle_within_window_listed_and_beyond_dropped(self):
        home = make_home(
            self.root,
            [thread("t1"), thread("t2")],
            [
                turn("t1", "u1", "completed", NOW - 40 * 60, NOW - 29 * 60),
                turn("t2", "u2", "completed", NOW - 40 * 60, NOW - 31 * 60),
            ],
        )
        sessions = self.read(home, idle_minutes=30, t1=LOCK_OPEN, t2=LOCK_OPEN)
        self.assertEqual([(s["session_id"], s["status"]) for s in sessions], [("t1", "idle")])

    def test_marker_for_current_turn_is_waiting(self):
        home = make_home(
            self.root,
            [thread("t1")],
            [turn("t1", "u1", "completed", NOW - 300, NOW - 200), turn("t1", "u2", "inProgress", NOW - 10)],
        )
        self.mark("t1", "u2", tool="shell")
        sessions = self.read(home, t1=LOCK_OPEN)
        self.assertEqual(
            (sessions[0]["status"], sessions[0]["tool"], sessions[0]["turn_id"]), ("waiting", "shell", "u2")
        )

    def test_marker_ignored_for_other_turn_or_later_item(self):
        home = make_home(
            self.root,
            [thread("t1")],
            [turn("t1", "u1", "completed", NOW - 300, NOW - 200), turn("t1", "u2", "inProgress", NOW - 10)],
            items=[("t1", "u2", int(NOW * 1000) - 1000, None)],
        )
        self.mark("t1", "u1")
        self.assertEqual(self.read(home, t1=LOCK_OPEN)[0]["status"], "working")
        # Marked at NOW - 5 s, but an item of the same turn started at NOW - 1 s: answered.
        self.mark("t1", "u2")
        self.assertEqual(self.read(home, t1=LOCK_OPEN)[0]["status"], "working")
        self.assertEqual(self.read(home, items_live=False, t1=LOCK_OPEN)[0]["status"], "waiting")

    def test_marker_ignored_once_the_turn_ends(self):
        home = make_home(self.root, [thread("t1")], [turn("t1", "u2", "completed", NOW - 30, NOW - 5)])
        self.mark("t1", "u2")
        self.assertEqual(self.read(home, t1=LOCK_OPEN)[0]["status"], "idle")

    def test_turn_left_over_by_a_crash_is_not_working(self):
        # t1's turn has said inProgress for a month (its process died), and reopening the chat
        # took its lock again; t2 has run for 4 hours but finished an item 10 minutes ago.
        home = make_home(
            self.root,
            [thread("t1"), thread("t2")],
            [turn("t1", "u1", "inProgress", NOW - 30 * 86400), turn("t2", "u2", "inProgress", NOW - 4 * 3600)],
            items=[("t2", "u2", int((NOW - 900) * 1000), int((NOW - 600) * 1000))],
        )
        sessions = self.read(home, t1=LOCK_OPEN, t2=LOCK_OPEN)
        self.assertEqual([(s["session_id"], s["status"]) for s in sessions], [("t2", "working")])

    def test_subagent_rolls_into_parent(self):
        home = make_home(
            self.root,
            [thread("p", title="parent"), thread("c", thread_source="subagent")],
            [turn("p", "u1", "completed", NOW - 60, NOW - 50), turn("c", "u9", "inProgress", NOW - 20)],
            edges=[("p", "c")],
        )
        sessions = self.read(home, p=LOCK_OPEN, c=LOCK_OPEN)
        self.assertEqual([(s["session_id"], s["status"]) for s in sessions], [("p", "working")])

    def test_subagent_waiting_makes_its_parent_wait(self):
        home = make_home(
            self.root,
            [thread("p"), thread("c", thread_source="subagent")],
            [turn("p", "u1", "inProgress", NOW - 60), turn("c", "u9", "inProgress", NOW - 20)],
            edges=[("p", "c")],
        )
        self.mark("c", "u9", tool="apply_patch")
        sessions = self.read(home, p=LOCK_OPEN, c=LOCK_OPEN)
        self.assertEqual(
            [(s["session_id"], s["status"], s["tool"]) for s in sessions], [("p", "waiting", "apply_patch")]
        )

    def test_child_of_a_closed_parent_is_listed_itself(self):
        home = make_home(
            self.root,
            [thread("p"), thread("c", source='{"subagent": {}}')],
            [turn("c", "u9", "inProgress", NOW - 20)],
            edges=[("p", "c")],
        )
        sessions = self.read(home, c=LOCK_OPEN)
        self.assertEqual([(s["session_id"], s["status"]) for s in sessions], [("c", "working")])

    def test_name_falls_back_to_title_then_folder(self):
        home = make_home(
            self.root,
            [
                thread("t1", name="named", title="titled"),
                thread("t2", title="titled"),
                thread("t3", cwd="D:\\work\\yasb\\"),
                thread("t4"),
            ],
            [turn(t, "u", "inProgress", NOW - 5) for t in ("t1", "t2", "t3", "t4")],
        )
        sessions = self.read(home, t1=LOCK_OPEN, t2=LOCK_OPEN, t3=LOCK_OPEN, t4=LOCK_OPEN)
        names = {s["session_id"]: s["name"] for s in sessions}
        self.assertEqual(names, {"t1": "named", "t2": "titled", "t3": "yasb", "t4": "session"})

    def test_sessions_carry_their_app_and_newest_comes_first(self):
        home = make_home(
            self.root,
            [thread("old", originator="Claude Code", source="vscode"), thread("new", originator="codex-tui")],
            [turn("old", "u1", "completed", NOW - 600, NOW - 500), turn("new", "u2", "inProgress", NOW - 5)],
        )
        sessions = self.read(home, old=LOCK_OPEN, new=LOCK_OPEN)
        self.assertEqual([(s["session_id"], s["app"]) for s in sessions], [("new", "terminal"), ("old", "Claude Code")])

    def test_app_hint(self):
        self.assertEqual(app_hint("Claude Code", "vscode"), "Claude Code")
        self.assertEqual(app_hint("Codex Desktop", "vscode"), "Desktop")
        self.assertEqual(app_hint("codex-tui", "cli"), "terminal")
        self.assertEqual(app_hint("codex_exec", "exec"), "exec")
        self.assertEqual(app_hint(None, "cli"), "terminal")
        self.assertEqual(app_hint(None, "exec"), "exec")
        self.assertEqual(app_hint(None, "vscode"), "")

    def test_turn_events_finished_and_failed(self):
        def s(session_id: str, turn_id: str, status: str) -> dict[str, Any]:
            return {"session_id": session_id, "turn_id": turn_id, "turn_status": status}

        before = [s("a", "u1", "inProgress"), s("b", "u7", "inProgress"), s("c", "u3", "inProgress")]
        after = [s("a", "u1", "completed"), s("b", "u7", "interrupted"), s("c", "u4", "inProgress")]
        self.assertEqual(sorted(turn_events(before, after)), ["failed", "finished"])
        self.assertEqual(turn_events(after, after), [])

    def test_missing_codex_home_reads_no_sessions(self):
        self.assertEqual(read_codex_sessions(str(self.root / "nope"), str(self.markers), NOW), [])

    def test_unreadable_database_returns_none(self):
        home = make_home(self.root, [thread("t1")], [turn("t1", "u1", "inProgress", NOW - 20)])
        (home / "state_5.sqlite").write_bytes(b"this is not a database" * 100)
        self.assertIsNone(read_codex_sessions(str(home), str(self.markers), NOW, probe=probe(t1=LOCK_OPEN)))

    def test_marker_with_bom_and_garbage(self):
        marker = {"turn_id": "u2", "tool_name": "shell", "at_ms": 5}
        (self.markers / "t1.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(marker).encode())
        self.assertEqual(read_marker(str(self.markers), "t1"), marker)
        (self.markers / "t2.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(read_marker(str(self.markers), "t2"))
        self.assertIsNone(read_marker(str(self.markers), "t3"))


class CodexSessionsConfigTest(unittest.TestCase):
    def test_defaults_are_off_and_match_the_spec(self):
        config = CodexUsageConfig()
        self.assertFalse(config.sessions.enabled)
        self.assertEqual(
            (config.sessions.idle_minutes, config.sessions.poll_interval, config.sessions.max_rows), (30, 2, 6)
        )


class CodexSessionsServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtCore import QCoreApplication

        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_failed_reads_keep_the_list_then_give_up(self):
        session = {"session_id": "t1", "status": "working", "turn_id": "u1", "turn_status": "inProgress"}
        session.update(name="fix tests", tool="")
        reads = [[session]]

        def fake_read(*a: Any, **k: Any) -> list[dict[str, str]] | None:
            return reads.pop(0) if reads else None

        with mock.patch.object(sessions_module, "read_codex_sessions", fake_read):
            service = sessions_module.CodexSessionsService(60, 30, (60, 30))
            got: list[list[dict[str, Any]]] = []
            service.data_ready.connect(got.append)
            self.assertEqual(service.latest(), [session])
            now = [1000.0]
            service._clock = lambda: now[0]
            service._last_good = now[0]
            # A busy database for a moment: the last good list stays.
            for now[0] in (1010.0, 1029.0):
                service._tick()
            self.assertEqual((got, service.latest()), ([], [session]))
            # Still unreadable half a minute on: show nothing rather than a frozen "working".
            now[0] = 1031.0
            service._tick()
            self.assertEqual((got, service.latest()), ([[]], []))
            now[0] = 1040.0
            service._tick()
            self.assertEqual(got, [[]])
            # Readable again: the list comes back.
            reads.append([session])
            service._tick()
            self.assertEqual(got, [[], [session]])
            service._timer.stop()


if __name__ == "__main__":
    unittest.main()
