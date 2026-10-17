"""Live Codex sessions, read from the files Codex keeps for itself.

While a Codex process has a chat loaded it holds an OS lock on
``<home>/thread-writer-locks/<thread id>.lock``, and it deletes the file when it closes cleanly; a
file left behind by a crash can be read. Each chat's turns are in ``thread_history_<N>.sqlite``
(``thread_turns.status`` reads ``inProgress`` while Codex works, then ``completed``, ``failed``
or ``interrupted``), and its name, folder and the app that started it in ``state_<N>.sqlite``.
Both databases are opened read-only. Approval prompts are not on disk at all: the optional Codex
hook (``assets/scripts/codex-waiting-hook.ps1``) leaves a marker per session in YASB's app-data
folder while one is pending.

One Codex process (Claude Code's Codex plugin, the desktop app) can keep finished chats loaded
for hours, so an idle session only counts while its last turn is under ``idle_minutes`` old.
"""

import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, ClassVar

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.utils.system import app_data_path
from core.widgets.services.claude_usage.sessions import STATUS_IDLE, STATUS_WAITING, STATUS_WORKING, count_sessions

__all__ = [
    "LOCK_MISSING",
    "LOCK_OPEN",
    "LOCK_STALE",
    "STATUS_IDLE",
    "STATUS_WAITING",
    "STATUS_WORKING",
    "CodexSessionsService",
    "app_hint",
    "codex_home",
    "count_sessions",
    "latest_db",
    "lock_state",
    "read_codex_sessions",
    "read_marker",
    "turn_events",
]

logger = logging.getLogger("codex_usage")

LOCK_OPEN = "open"
LOCK_STALE = "stale"
LOCK_MISSING = "missing"
# Windows reports a held lock as one of these when the file is opened or read.
_SHARING_VIOLATION = 32
_LOCK_VIOLATION = 33

_APPS = {"Claude Code": "Claude Code", "Codex Desktop": "Desktop", "codex-tui": "terminal", "codex_exec": "exec"}
_SOURCES = {"cli": "terminal", "exec": "exec"}
_FAILED = ("failed", "interrupted")
# Waiting beats working beats idle when a sub-agent is rolled into its parent.
_RANK = {STATUS_IDLE: 0, STATUS_WORKING: 1, STATUS_WAITING: 2}
# A crash leaves its turn inProgress for good, and reopening that chat takes its lock again, so a
# running turn only counts while it shows a sign of life: started, or an item of it finished,
# within this long. Items land as they finish, so a quiet stretch is one long-running command.
_STALE_TURN_S = 3 * 3600
# How long the poller keeps its last good list while the databases cannot be read.
_GIVE_UP_S = 30


def codex_home() -> str:
    return os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")


def latest_db(home: str, stem: str) -> str | None:
    """The newest schema of a Codex database: ``<stem>_<N>.sqlite`` with the highest ``N``."""
    pattern = re.compile(rf"{re.escape(stem)}_(\d+)\.sqlite$")
    try:
        names = os.listdir(home)
    except OSError:
        return None
    best = max(((int(m.group(1)), name) for name in names if (m := pattern.match(name))), default=None)
    return os.path.join(home, best[1]) if best else None


def lock_state(path: str) -> str:
    """Whether a Codex process holds this lock file: reading it never takes the lock."""
    try:
        with open(path, "rb") as f:
            f.read(1)
    except FileNotFoundError:
        return LOCK_MISSING
    except PermissionError:
        # A held lock reads as EACCES through the C runtime, with no winerror attached.
        return LOCK_OPEN
    except OSError as e:
        return LOCK_OPEN if getattr(e, "winerror", None) in (_SHARING_VIOLATION, _LOCK_VIOLATION) else LOCK_MISSING
    return LOCK_STALE


def read_marker(directory: str, thread_id: str) -> dict[str, Any] | None:
    """The approval marker the hook left for a session, or None. PowerShell 5.1 writes a BOM."""
    try:
        with open(os.path.join(directory, f"{thread_id}.json"), encoding="utf-8-sig") as f:
            data = json.load(f)
        return {
            "turn_id": str(data["turn_id"]),
            "tool_name": str(data.get("tool_name") or ""),
            "at_ms": int(data["at_ms"]),
        }
    except OSError, ValueError, KeyError, TypeError:
        return None


def app_hint(originator: str | None, source: str | None) -> str:
    """Which app started a chat, in a word or two; older chats only have their ``source``."""
    if originator:
        return _APPS.get(originator, originator)
    return _SOURCES.get(source or "", "")


def _connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.2)


def _marks(ids: list[str]) -> str:
    return ", ".join("?" * len(ids))


def _read_state(path: str, ids: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    con = _connect(path)
    try:
        threads = {
            row[0]: {
                "name": row[1],
                "title": row[2],
                "cwd": row[3],
                "source": row[4],
                "originator": row[5],
                "thread_source": row[6],
                "updated_at": row[7],
            }
            for row in con.execute(
                "select id, name, title, cwd, source, originator, thread_source, updated_at"
                f" from threads where id in ({_marks(ids)})",
                ids,
            )
        }
        parents = {
            child: parent
            for parent, child in con.execute(
                f"select parent_thread_id, child_thread_id from thread_spawn_edges where child_thread_id in ({_marks(ids)})",
                ids,
            )
        }
    finally:
        con.close()
    return threads, parents


def _latest_turns(con: sqlite3.Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    turns: dict[str, dict[str, Any]] = {}
    for thread_id, turn_id, status, started, completed in con.execute(
        "select thread_id, turn_id, status, started_at, completed_at from thread_turns"
        f" where thread_id in ({_marks(ids)}) order by started_at, rollout_ordinal",
        ids,
    ):
        turns[thread_id] = {"turn_id": turn_id, "status": status, "started_at": started, "completed_at": completed}
    return turns


def _last_sign_of_life(con: sqlite3.Connection, thread_id: str, turn: dict[str, Any]) -> float:
    """When a turn last showed it was running, in epoch seconds: its start or its latest item."""
    (latest_ms,) = con.execute(
        "select max(max(coalesce(completed_at_ms, 0), coalesce(created_at_ms, 0)))"
        " from thread_items where thread_id = ? and turn_id = ?",
        (thread_id, turn["turn_id"]),
    ).fetchone()
    return max(float(turn["started_at"] or 0), (latest_ms or 0) / 1000)


def _answered_since(con: sqlite3.Connection, thread_id: str, turn_id: str, since_ms: int) -> bool:
    """Whether the turn moved on after the approval prompt: an item started or finished since."""
    (latest,) = con.execute(
        "select max(max(coalesce(started_at_ms, 0), coalesce(completed_at_ms, 0)))"
        " from thread_items where thread_id = ? and turn_id = ?",
        (thread_id, turn_id),
    ).fetchone()
    return latest is not None and latest > since_ms


def _is_child(row: dict[str, Any]) -> bool:
    return row["thread_source"] == "subagent" or str(row["source"] or "").startswith("{")


def read_codex_sessions(
    home: str,
    markers_dir: str,
    now: float,
    idle_minutes: int = 30,
    probe=lock_state,
    items_live: bool = True,
) -> list[dict[str, Any]] | None:
    """Every live Codex session, newest first; None when a database cannot be read right now."""
    locks = os.path.join(home, "thread-writer-locks")
    try:
        names = [name for name in os.listdir(locks) if name.endswith(".lock")]
    except OSError:
        return []
    state_db = latest_db(home, "state")
    open_ids = [name[:-5] for name in names if probe(os.path.join(locks, name)) == LOCK_OPEN]
    if state_db is None or not open_ids:
        return []
    history_db = latest_db(home, "thread_history")

    try:
        threads, parents = _read_state(state_db, open_ids)
        con = _connect(history_db) if history_db else None
        try:
            turns = _latest_turns(con, open_ids) if con else {}
            states: dict[str, tuple[str, str]] = {}
            for thread_id, turn in turns.items():
                if turn["status"] != "inProgress" or now - _last_sign_of_life(con, thread_id, turn) > _STALE_TURN_S:
                    continue
                marker = read_marker(markers_dir, thread_id)
                waiting = (
                    marker is not None
                    and marker["turn_id"] == turn["turn_id"]
                    and not (items_live and _answered_since(con, thread_id, turn["turn_id"], marker["at_ms"]))
                )
                states[thread_id] = (STATUS_WAITING, marker["tool_name"]) if waiting else (STATUS_WORKING, "")
        finally:
            if con is not None:
                con.close()
    except sqlite3.Error as e:
        logger.debug("Codex session databases unreadable: %s", e)
        return None

    open_set = set(open_ids)
    rolled: dict[str, tuple[str, str]] = {}
    listed: list[str] = []
    for thread_id in open_ids:
        row = threads.get(thread_id)
        if row is None:
            continue  # its row lands a moment after the lock; the next poll picks it up
        parent = parents.get(thread_id)
        if _is_child(row) and parent in open_set and parent in threads:
            state = states.get(thread_id)
            if state and _RANK[state[0]] > _RANK[rolled.get(parent, (STATUS_IDLE, ""))[0]]:
                rolled[parent] = state
            continue
        listed.append(thread_id)

    sessions = []
    for thread_id in listed:
        row = threads[thread_id]
        turn = turns.get(thread_id, {})
        status, tool = states.get(thread_id, (STATUS_IDLE, ""))
        child = rolled.get(thread_id)
        if child and _RANK[child[0]] > _RANK[status]:
            status, tool = child
        last_active = max(turn.get("completed_at") or 0, turn.get("started_at") or 0, row["updated_at"] or 0)
        if status == STATUS_IDLE and now - last_active > idle_minutes * 60:
            continue
        cwd = str(row["cwd"] or "")
        name = (
            str(row["name"] or "").strip()
            or str(row["title"] or "").strip()
            or os.path.basename(cwd.rstrip("\\/"))
            or "session"
        )
        sessions.append(
            {
                "session_id": thread_id,
                "name": name,
                "cwd": cwd,
                "status": status,
                "app": app_hint(row["originator"], row["source"]),
                "tool": tool,
                "turn_id": str(turn.get("turn_id") or ""),
                "turn_status": str(turn.get("status") or ""),
                "last_active": float(last_active),
            }
        )
    return sorted(sessions, key=lambda s: (-s["last_active"], s["session_id"]))


def turn_events(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    """``finished`` / ``failed`` for each session whose running turn ended between two reads."""
    previous = {s["session_id"]: (s["turn_id"], s["turn_status"]) for s in before}
    events = []
    for session in after:
        turn_id, status = previous.get(session["session_id"], ("", ""))
        if status != "inProgress" or session["turn_id"] != turn_id:
            continue
        if session["turn_status"] == "completed":
            events.append("finished")
        elif session["turn_status"] in _FAILED:
            events.append("failed")
    return events


class CodexSessionsService(QObject):
    """Shared poller for Codex's sessions, reference-counted like ``ClaudeSessionsService``.

    One read opens two small databases and probes a few lock files: a few milliseconds, so it
    runs on the GUI thread. A read that fails (a database mid-write, a newer schema) keeps the
    last good list rather than flashing "no sessions".
    """

    data_ready = pyqtSignal(list)

    _instances: ClassVar[dict[tuple, CodexSessionsService]] = {}

    @classmethod
    def get_instance(cls, poll_interval_s: int, idle_minutes: int) -> CodexSessionsService:
        key = (int(poll_interval_s), int(idle_minutes))
        inst = cls._instances.get(key)
        if inst is None:
            inst = cls(poll_interval_s=int(poll_interval_s), idle_minutes=int(idle_minutes), _key=key)
            cls._instances[key] = inst
        inst._refcount += 1
        return inst

    def __init__(self, poll_interval_s: int, idle_minutes: int, _key: tuple):
        super().__init__()
        self._key = _key
        self._refcount = 0
        self._idle_minutes = idle_minutes
        self._home = codex_home()
        self._markers = str(app_data_path("codex-waiting"))
        self._data: list[dict[str, Any]] = []
        self._signature: tuple = ()
        self._clock = time.monotonic
        self._last_good = self._clock()

        self._timer = QTimer(self)
        self._timer.setInterval(max(poll_interval_s, 1) * 1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()

    def latest(self) -> list[dict[str, Any]]:
        return self._data

    def release(self) -> None:
        self._refcount -= 1
        if self._refcount > 0:
            return
        self._timer.stop()
        CodexSessionsService._instances.pop(self._key, None)
        self.deleteLater()

    def refresh_now(self) -> None:
        self._tick()

    def _tick(self) -> None:
        try:
            sessions = read_codex_sessions(self._home, self._markers, time.time(), self._idle_minutes)
        except Exception as e:
            logger.debug("Codex session scan failed: %s", e)
            sessions = None
        if sessions is None:
            # A database mid-write reads again in a moment; one that stays unreadable (a newer
            # schema, a corrupt file) must not leave a session frozen as working.
            if self._data and self._clock() - self._last_good > _GIVE_UP_S:
                logger.warning("Codex sessions unreadable for %ss; showing none until they read again", _GIVE_UP_S)
                self._data = []
                self._signature = ()
                self.data_ready.emit([])
            return
        self._last_good = self._clock()
        # Only announce a change: the popup rebuilds its rows on every emit.
        signature = tuple(
            (s["session_id"], s["status"], s["turn_id"], s["turn_status"], s["name"], s["tool"]) for s in sessions
        )
        if signature == self._signature:
            return
        self._signature = signature
        self._data = sessions
        self.data_ready.emit(sessions)
