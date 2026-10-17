"""Live Claude Code sessions, read from the registry Claude Code keeps for itself.

Every Claude Code process writes ``<config dir>/sessions/<pid>.json`` with its name, folder
and a ``status`` of ``busy`` (working), ``waiting`` (needs you: a permission, a question, a
dialog - see ``waitingFor``) or idle. A file can outlive its process, so one only counts while
a process with that pid is alive *and* started when the file says it did: ``procStart`` is the
process's Windows FILETIME, which keeps a recycled pid from resurrecting a dead session.

A machine can run several Claude accounts side by side (``CLAUDE_CONFIG_DIR`` pointing at
``~/.claude-personal`` and so on), and Clawd reacts to all of them, so every ``~/.claude*``
directory with a ``sessions`` folder is scanned unless the config names the directories.
"""

import ctypes
import json
import logging
import os
from ctypes import wintypes
from glob import glob
from typing import Any, ClassVar

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

logger = logging.getLogger("claude_usage")

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
# procStart and the live start time can disagree by rounding; the original allows 5 s.
_START_DRIFT = 5 * 10_000_000

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.GetExitCodeProcess.restype = wintypes.BOOL
_kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
_kernel32.GetProcessTimes.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

STATUS_WORKING = "working"
STATUS_WAITING = "waiting"
STATUS_IDLE = "idle"


def process_start(pid: int) -> int | None:
    """The live process's start FILETIME; 0 when it is alive but unreadable; None when gone."""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means the process exists (e.g. an elevated one) - just not its times.
        return 0 if ctypes.get_last_error() == _ERROR_ACCESS_DENIED else None
    try:
        code = wintypes.DWORD()
        if _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != _STILL_ACTIVE:
            return None
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not _kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return 0
        return (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        _kernel32.CloseHandle(handle)


def session_dirs(configured: list[str] | None = None) -> list[str]:
    """The ``sessions`` folders to scan: the configured config dirs, or every Claude one found."""
    if configured:
        roots = [os.path.expandvars(os.path.expanduser(p)) for p in configured]
    else:
        home = os.path.expanduser("~")
        roots = [os.environ.get("CLAUDE_CONFIG_DIR") or "", os.path.join(home, ".claude")]
        roots += sorted(glob(os.path.join(home, ".claude-*")))
    seen: set[str] = set()
    dirs = []
    for root in roots:
        if not root:
            continue
        path = os.path.normcase(os.path.abspath(os.path.join(root, "sessions")))
        if path not in seen and os.path.isdir(path):
            seen.add(path)
            dirs.append(path)
    return dirs


def parse_session(data: dict[str, Any]) -> dict[str, Any] | None:
    """One registry entry as the widget uses it, or None when it is not a session record."""
    try:
        pid = int(data.get("pid") or 0)
    except TypeError, ValueError:
        return None
    if pid <= 0:
        return None
    cwd = str(data.get("cwd") or "")
    name = str(data.get("name") or "").strip() or os.path.basename(cwd.rstrip("\\/")) or "session"
    raw_status = str(data.get("status") or "")
    status = {"busy": STATUS_WORKING, "waiting": STATUS_WAITING}.get(raw_status, STATUS_IDLE)
    try:
        proc_start = int(data.get("procStart") or 0)
    except TypeError, ValueError:
        proc_start = 0
    return {
        "pid": pid,
        "session_id": str(data.get("sessionId") or ""),
        "name": name,
        "cwd": cwd,
        "status": status,
        "waiting_for": str(data.get("waitingFor") or ""),
        "kind": str(data.get("kind") or ""),
        "started_at": data.get("startedAt") or 0,
        "proc_start": proc_start,
    }


def is_live(session: dict[str, Any], start_of=process_start) -> bool:
    """Whether the session's process is still the one that wrote the file."""
    started = start_of(session["pid"])
    if started is None:
        return False
    if started and session["proc_start"]:
        return abs(started - session["proc_start"]) <= _START_DRIFT
    return True


def read_sessions(dirs: list[str], start_of=process_start) -> list[dict[str, Any]]:
    """Every live session in ``dirs``, oldest first, each listed once."""
    sessions: dict[str, dict[str, Any]] = {}
    for directory in dirs:
        try:
            names = [n for n in os.listdir(directory) if n.endswith(".json")]
        except OSError:
            continue
        for filename in names:
            try:
                with open(os.path.join(directory, filename), encoding="utf-8") as f:
                    session = parse_session(json.load(f))
            except Exception:
                continue  # half-written or not a session file
            if session is None or not is_live(session, start_of):
                continue
            sessions.setdefault(session["session_id"] or f"pid:{session['pid']}", session)
    return sorted(sessions.values(), key=lambda s: (s["started_at"], s["pid"]))


def count_sessions(sessions: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(sessions), STATUS_WORKING: 0, STATUS_WAITING: 0, STATUS_IDLE: 0}
    for session in sessions:
        counts[session["status"]] += 1
    return counts


class ClaudeSessionsService(QObject):
    """Shared poller for the session registry, reference-counted like ``ClaudeUsageService``.

    Reading a handful of small files and asking Windows about their pids takes well under a
    millisecond, so this runs on the GUI thread rather than paying for a worker thread.
    """

    data_ready = pyqtSignal(list)

    _instances: ClassVar[dict[tuple, ClaudeSessionsService]] = {}

    @classmethod
    def get_instance(cls, poll_interval_s: int, dirs: list[str]) -> ClaudeSessionsService:
        key = (int(poll_interval_s), tuple(dirs))
        inst = cls._instances.get(key)
        if inst is None:
            inst = cls(poll_interval_s=int(poll_interval_s), dirs=list(dirs), _key=key)
            cls._instances[key] = inst
        inst._refcount += 1
        return inst

    def __init__(self, poll_interval_s: int, dirs: list[str], _key: tuple):
        super().__init__()
        self._key = _key
        self._refcount = 0
        self._configured_dirs = dirs
        self._dirs = session_dirs(dirs)
        self._data: list[dict[str, Any]] = []
        self._signature: tuple = ()
        self._ticks = 0

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
        ClaudeSessionsService._instances.pop(self._key, None)
        self.deleteLater()

    def refresh_now(self) -> None:
        self._dirs = session_dirs(self._configured_dirs)
        self._tick()

    def _tick(self) -> None:
        # A config dir created after startup (a new account signing in) is picked up within a
        # minute or so, without re-globbing the home folder on every poll.
        self._ticks += 1
        if self._ticks % 30 == 0:
            self._dirs = session_dirs(self._configured_dirs)
        try:
            sessions = read_sessions(self._dirs)
        except Exception as e:
            logger.debug("session scan failed: %s", e)
            return
        # Only announce a change: the popup rebuilds its rows on every emit.
        signature = tuple((s["session_id"], s["pid"], s["status"], s["name"], s["waiting_for"]) for s in sessions)
        if signature == self._signature:
            return
        self._signature = signature
        self._data = sessions
        self.data_ready.emit(sessions)
