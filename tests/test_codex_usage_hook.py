"""Tests for the optional Codex hook that marks a session as waiting for approval.

The real script runs under Windows PowerShell 5.1, the way Codex runs it, with LOCALAPPDATA
pointed at a temporary folder, and its marker is read back with the widget's own reader.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
SCRIPT = SRC_ROOT / "assets" / "scripts" / "codex-waiting-hook.ps1"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.widgets.services.codex_usage.sessions import read_marker  # noqa: E402

SID = "019a1b2c-3d4e-7f80-9a1b-2c3d4e5f6a7b"


class CodexWaitingHookTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.appdata = Path(self._tmp.name)
        self.markers = self.appdata / "YASB" / "codex-waiting"

    def tearDown(self):
        self._tmp.cleanup()

    def run_hook(self, payload: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**os.environ, "LOCALAPPDATA": str(self.appdata)},
            timeout=60,
        )

    def test_permission_request_writes_a_marker_the_widget_reads(self):
        result = self.run_hook(
            {"hook_event_name": "PermissionRequest", "session_id": SID, "turn_id": "u2", "tool_name": "shell"}
        )
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        marker = read_marker(str(self.markers), SID)
        assert marker is not None
        self.assertEqual((marker["turn_id"], marker["tool_name"]), ("u2", "shell"))
        self.assertGreater(marker["at_ms"], 1_700_000_000_000)

    def test_post_tool_use_and_stop_remove_it(self):
        for event in ("PostToolUse", "Stop"):
            self.run_hook(
                {"hook_event_name": "PermissionRequest", "session_id": SID, "turn_id": "u2", "tool_name": "shell"}
            )
            self.assertIsNotNone(read_marker(str(self.markers), SID))
            result = self.run_hook({"hook_event_name": event, "session_id": SID})
            self.assertIsNone(read_marker(str(self.markers), SID), event)
            self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_bad_session_id_writes_nothing(self):
        result = self.run_hook(
            {"hook_event_name": "PermissionRequest", "session_id": "..\\..\\evil", "turn_id": "u", "tool_name": "x"}
        )
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse(self.markers.exists() and any(self.markers.iterdir()))

    def test_garbage_input_still_exits_quietly(self):
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)],
            input="not json at all",
            capture_output=True,
            text=True,
            env={**os.environ, "LOCALAPPDATA": str(self.appdata)},
            timeout=60,
        )
        self.assertEqual((result.returncode, result.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
